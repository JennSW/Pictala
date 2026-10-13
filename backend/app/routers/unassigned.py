"""Endpoints for checklist-less photos (issue #35) -- photos with no
eBird checklist at all, either permanently (a captive/indoor bird photo
that will never be a countable eBird sighting) or not yet (a real
outing whose checklist hasn't been uploaded). See
app/services/photo_clusters.py for how these get grouped, and
models.py's Match.checklist_id docstring for why null instead of a
sentinel id.

Deliberately a separate, smaller set of endpoints rather than reusing
/match/{checklist_id}/... -- there's no checklist here for a suggestion
to be constrained against, so there's no "tier 1: on this checklist"
step, just eBird-taxonomy resolution (tier 2) or a plain note (tier 3),
same as the tail of accept-fallback's logic.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Match, Photo, AiSuggestionLog
from app.schemas import ClusterSummary, ClusterDetail, MatchOut, FallbackSuggestion, photo_out
from app.services.photo_clusters import compute_clusters, get_cluster
from app.services.ebird_taxonomy import find_species, resolve_guess
from app.services.duplicate_detection import get_duplicates_for_photo
from app.services.photo_dates import effective_datetime
from app.services.species_classifier import (
    guess_species_unconstrained,
    guess_species_unconstrained_batch,
    SpeciesClassifierNotConfigured,
    SpeciesClassifierError,
)

router = APIRouter(prefix="/unassigned", tags=["unassigned"])


def _possible_duplicate(db: Session, photo: Photo) -> dict | None:
    others = get_duplicates_for_photo(db, photo)
    if not others:
        return None
    return {
        "other_photo_ids": [o.id for o in others],
        "other_flickr_urls": [photo_out(o).flickr_url for o in others],
    }


def _match_out_for_photo(db: Session, photo: Photo) -> dict:
    match = (
        db.query(Match)
        .filter(Match.photo_id == photo.id, Match.checklist_id.is_(None))
        .one_or_none()
    )
    return {
        "checklist_id": None,
        "photo": photo_out(photo),
        "observation": None,
        "method": match.method if match else "unassigned",
        "confidence": match.confidence if match else 0.0,
        "fallback_common_name": match.fallback_common_name if match else None,
        "fallback_scientific_name": match.fallback_scientific_name if match else None,
        "ebird_checklist_url": None,
        "reviewed_at": match.reviewed_at.isoformat() if match and match.reviewed_at else None,
        "timezone_mismatch": None,
        "possible_duplicate": _possible_duplicate(db, photo),
    }


@router.get("", response_model=list[ClusterSummary])
def list_clusters(db: Session = Depends(get_db)):
    return [
        {"id": c["id"], "date": c["date"], "photo_count": len(c["photo_ids"])}
        for c in compute_clusters(db)
    ]


@router.get("/{cluster_id}", response_model=ClusterDetail)
def get_cluster_detail(cluster_id: str, db: Session = Depends(get_db)):
    cluster = get_cluster(db, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found")
    photos_by_id = {p.id: p for p in db.query(Photo).filter(Photo.id.in_(cluster["photo_ids"])).all()}
    ordered = [photos_by_id[pid] for pid in cluster["photo_ids"] if pid in photos_by_id]
    return {
        "id": cluster["id"],
        "date": cluster["date"],
        "matches": [_match_out_for_photo(db, p) for p in ordered],
    }


@router.post("/{cluster_id}/suggest/{photo_id}", response_model=FallbackSuggestion)
def suggest_for_photo(cluster_id: str, photo_id: int, db: Session = Depends(get_db)):
    """Unconstrained guess -- nothing persisted yet, same shape as the
    checklist-scoped suggest-fallback endpoint minus any checklist
    context (there isn't one)."""
    photo = db.query(Photo).filter(Photo.id == photo_id).one_or_none()
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    if not photo.url_medium:
        raise HTTPException(status_code=400, detail="This photo has no image URL to look at")

    try:
        result = guess_species_unconstrained(photo.url_medium, photo.title, photo.tags)
    except SpeciesClassifierNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SpeciesClassifierError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    common_name, scientific_name, species_code, is_other = resolve_guess(result["common_name"])

    return FallbackSuggestion(
        photo_id=photo_id,
        checklist_id=None,
        is_bird=result["is_bird"],
        common_name=common_name,
        scientific_name=scientific_name,
        species_code=species_code,
        confidence=result["confidence"],
        reasoning=result["reasoning"],
        ebird_checklist_url=None,
        is_other=is_other,
    )


class SuggestBatchRequest(BaseModel):
    photo_ids: list[int]


@router.post("/{cluster_id}/suggest-batch", response_model=list[FallbackSuggestion])
def suggest_batch(cluster_id: str, body: SuggestBatchRequest, db: Session = Depends(get_db)):
    """Batch version of suggest (issue #5) -- one Claude call for every
    checked photo instead of one round trip each. Particularly useful
    here: a checklist-less cluster like a 50+ photo indoor falconry
    session is exactly the "many photos, one at a time" problem #5 was
    filed for. Same "nothing persisted yet" contract as the single-photo
    version."""
    photos = db.query(Photo).filter(Photo.id.in_(body.photo_ids)).all()
    photos_by_id = {p.id: p for p in photos if p.url_medium}
    if not photos_by_id:
        return []

    try:
        results = guess_species_unconstrained_batch(
            [
                {"photo_id": p.id, "url": p.url_medium, "title": p.title, "tags": p.tags}
                for p in photos_by_id.values()
            ]
        )
    except SpeciesClassifierNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (SpeciesClassifierError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    suggestions = []
    for r in results:
        common_name, scientific_name, species_code, is_other = resolve_guess(r["common_name"])
        suggestions.append(
            FallbackSuggestion(
                photo_id=r["photo_id"],
                checklist_id=None,
                is_bird=r["is_bird"],
                common_name=common_name,
                scientific_name=scientific_name,
                species_code=species_code,
                confidence=r["confidence"],
                reasoning=r["reasoning"],
                ebird_checklist_url=None,
                is_other=is_other,
            )
        )
    return suggestions


class IdentifyRequest(BaseModel):
    common_name: str
    confidence: float = 1.0
    ai_suggested_common_name: str | None = None
    """Set only when this save follows the unconstrained guess above --
    see match.py's accept_fallback and AiSuggestionLog's docstring; same
    accepted/corrected logging, just for the checklist-less path."""


@router.post("/{cluster_id}/identify/{photo_id}", response_model=MatchOut)
def identify_photo(cluster_id: str, photo_id: int, body: IdentifyRequest, db: Session = Depends(get_db)):
    """A name was entered for a checklist-less photo -- typed by hand,
    or accepted from the unconstrained guess above. Resolves against
    eBird's full taxonomy (tier 2) or falls back to a plain Note (tier
    3) -- there's no tier 1 (on this checklist), since there's no
    checklist. Same resolution rule as accept-fallback's tail, minus
    the step that doesn't apply here."""
    photo = db.query(Photo).filter(Photo.id == photo_id).one_or_none()
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    match = (
        db.query(Match)
        .filter(Match.photo_id == photo_id, Match.checklist_id.is_(None))
        .one_or_none()
    )
    if match is None:
        match = Match(checklist_id=None, photo_id=photo_id)
        db.add(match)

    name = body.common_name.strip()
    resolved = find_species(name)
    if resolved:
        match.fallback_common_name = resolved["common_name"]
        match.fallback_scientific_name = resolved["scientific_name"]
        match.fallback_species_code = resolved["species_code"]
    else:
        match.fallback_common_name = name
        match.fallback_scientific_name = None
        match.fallback_species_code = None
    match.observation_id = None
    match.confidence = body.confidence
    match.method = "ai_fallback"
    match.reviewed_at = datetime.utcnow()

    if body.ai_suggested_common_name is not None:
        matches_suggestion = match.fallback_common_name.strip().lower() == body.ai_suggested_common_name.strip().lower()
        db.add(
            AiSuggestionLog(
                photo_id=photo_id,
                checklist_id=None,
                kind="unconstrained",
                suggested_common_name=body.ai_suggested_common_name,
                confidence=body.confidence,
                outcome="accepted" if matches_suggestion else "corrected",
                final_common_name=None if matches_suggestion else match.fallback_common_name,
            )
        )

    db.commit()
    db.refresh(match)

    return _match_out_for_photo(db, photo)


class MoveRequest(BaseModel):
    to_cluster_id: str


@router.post("/{cluster_id}/move/{photo_id}")
def move_photo(cluster_id: str, photo_id: int, body: MoveRequest, db: Session = Depends(get_db)):
    """Moves a photo into a different checklist-less cluster by setting
    its date_taken to match the target cluster's earliest photo --
    clustering is purely date-proximity-driven (see photo_clusters.py),
    so this is the same "fix the underlying field, let derived behavior
    follow" approach the timezone-mismatch Adjust action uses, not a
    separate override concept. For a photo whose real capture time is
    known to be wrong or misleading (e.g. a re-exported duplicate that
    picked up a different timestamp than its sibling -- see issue #35),
    this is the actual fix, not a workaround."""
    photo = db.query(Photo).filter(Photo.id == photo_id).one_or_none()
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    target = get_cluster(db, body.to_cluster_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target cluster not found")

    target_photos = db.query(Photo).filter(Photo.id.in_(target["photo_ids"])).all()
    if not target_photos:
        raise HTTPException(status_code=400, detail="Target cluster is empty")

    # Effective datetime, not raw date_taken: the target cluster's real day may
    # come from its photos' titles (issue #34, see photo_dates.py).
    earliest = min(effective_datetime(p) for p in target_photos)
    photo.date_taken = earliest.strftime("%Y-%m-%d %H:%M:%S")
    db.commit()

    return {"date_taken": photo.date_taken}

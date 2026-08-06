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
from app.models import Match, Photo
from app.schemas import ClusterSummary, ClusterDetail, MatchOut, FallbackSuggestion, photo_out
from app.services.photo_clusters import compute_clusters, get_cluster
from app.services.ebird_taxonomy import find_species
from app.services.species_classifier import (
    guess_species_unconstrained,
    SpeciesClassifierNotConfigured,
    SpeciesClassifierError,
)

router = APIRouter(prefix="/unassigned", tags=["unassigned"])


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

    species_code = scientific_name = None
    is_other = False
    common_name = result["common_name"] or None
    if common_name:
        resolved = find_species(common_name)
        if resolved:
            common_name = resolved["common_name"]
            scientific_name = resolved["scientific_name"]
            species_code = resolved["species_code"]
        else:
            is_other = True

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


class IdentifyRequest(BaseModel):
    common_name: str
    confidence: float = 1.0


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
    db.commit()
    db.refresh(match)

    return _match_out_for_photo(db, photo)

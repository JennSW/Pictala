"""Strategy B endpoints: AI-assisted species suggestions, plus the manual
and fallback paths for when a photo doesn't match any of the outing's own
reported species.

Two-step by design, matching DESIGN.md section 4's "show the guess, let the
user confirm/reject... never silently trusting it":

  POST /match/{checklist_id}/suggest/{photo_id}   -- constrained guess, persist nothing
  POST /match/{checklist_id}/accept/{photo_id}    -- keep an AI suggestion
  POST /match/{checklist_id}/assign/{photo_id}    -- manually pick one of the
                                                       outing's own species,
                                                       no AI suggestion behind it
  POST /match/{checklist_id}/suggest-fallback/{photo_id} -- broader guess for a
                                                       photo matching nothing
                                                       reported on this outing
  POST /match/{checklist_id}/accept-fallback/{photo_id}  -- keep a fallback guess
  POST /match/{checklist_id}/reject/{photo_id}    -- say no to a constrained
                                                       AI suggestion

Accepting/rejecting a *constrained* suggestion never changes what's kept
about it -- accept always keeps Claude's own suggested species, reject
never writes a Match at all (nothing to undo, per the original design
here). What accept/reject/accept-fallback all now do is also log the
suggestion + outcome to AiSuggestionLog (2026-09-03), independent of the
Match row, so AI accuracy can be measured later -- see that model's
docstring and GET /stats/ai-accuracy in stats.py.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Checklist, Photo, Match, AiSuggestionLog
from app.schemas import (
    SpeciesSuggestion,
    AcceptSuggestionRequest,
    AssignSpeciesRequest,
    FallbackSuggestion,
    AcceptFallbackRequest,
    RejectSuggestionRequest,
    MatchOut,
    photo_out,
    ebird_checklist_url,
)
from app.services.outing_grouping import get_checklist_group
from app.services.ebird_taxonomy import find_species, resolve_guess
from app.services.species_classifier import (
    guess_species,
    guess_species_unconstrained,
    guess_species_unconstrained_batch,
    SpeciesClassifierNotConfigured,
    SpeciesClassifierError,
)
from app.services.timezone_check import check_mismatch
from app.services.matcher import run_rule_based_matching

router = APIRouter(prefix="/match", tags=["match"])


def _log_ai_suggestion(
    db: Session,
    *,
    photo_id: int,
    checklist_id: int | None,
    kind: str,
    suggested_common_name: str | None,
    confidence: float,
    outcome: str,
    final_common_name: str | None = None,
) -> None:
    """See AiSuggestionLog's docstring. Always logs when called -- callers
    decide whether a given save is worth logging at all (e.g. a
    from-scratch typed note, with no AI guess behind it, skips this
    entirely rather than calling in with an empty suggestion)."""
    db.add(
        AiSuggestionLog(
            photo_id=photo_id,
            checklist_id=checklist_id,
            kind=kind,
            suggested_common_name=suggested_common_name,
            confidence=confidence,
            outcome=outcome,
            final_common_name=final_common_name,
        )
    )


def _get_or_create_match(db: Session, checklist_id: int, photo_id: int) -> Match:
    match = (
        db.query(Match)
        .filter(Match.checklist_id == checklist_id, Match.photo_id == photo_id)
        .one_or_none()
    )
    if match is None:
        # Shouldn't normally happen (the photo got here via rule-based
        # matching first), but don't silently no-op -- create the row so
        # accepting/assigning always has a visible effect.
        match = Match(checklist_id=checklist_id, photo_id=photo_id)
        db.add(match)
    return match


@router.post("/{checklist_id}/suggest/{photo_id}", response_model=SpeciesSuggestion)
def suggest_species(checklist_id: int, photo_id: int, db: Session = Depends(get_db)):
    checklist = db.query(Checklist).filter(Checklist.id == checklist_id).one_or_none()
    if checklist is None:
        raise HTTPException(status_code=404, detail="Checklist not found")

    photo = db.query(Photo).filter(Photo.id == photo_id).one_or_none()
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    if not photo.url_medium:
        raise HTTPException(
            status_code=400, detail="This photo has no image URL to look at"
        )

    # Candidates come from the whole outing group (all checklists sharing
    # this one's date + Location ID, per docs/USER_STORIES.md's outing
    # grouping story), not just this single checklist -- a photo taken
    # during a multi-checklist trip should be checked against everything
    # reported on the trip, not whichever checklist it happened to land
    # under. De-dupe candidate species by common name (a checklist can
    # have more than one Observation row for the same species -- e.g.
    # re-imports, or multiple counts logged separately, or the same
    # species reported on two checklists in the group) while keeping the
    # mapping back to an observation_id for whichever one appears first.
    group = get_checklist_group(db, checklist)
    seen = {}
    for c in group:
        for obs in c.observations:
            seen.setdefault(obs.common_name, obs.id)
    candidate_names = list(seen.keys())

    if not candidate_names:
        raise HTTPException(
            status_code=400, detail="This outing has no species to suggest from"
        )

    try:
        result = guess_species(photo.url_medium, candidate_names)
    except SpeciesClassifierNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SpeciesClassifierError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    common_name = result["common_name"]
    suggested_observation_id = seen.get(common_name) if common_name else None

    return SpeciesSuggestion(
        photo_id=photo_id,
        checklist_id=checklist_id,
        candidate_common_names=candidate_names,
        suggested_observation_id=suggested_observation_id,
        suggested_common_name=common_name,
        confidence=result["confidence"],
        reasoning=result["reasoning"],
    )


@router.post("/{checklist_id}/accept/{photo_id}", response_model=MatchOut)
def accept_suggestion(
    checklist_id: int,
    photo_id: int,
    body: AcceptSuggestionRequest,
    db: Session = Depends(get_db),
):
    checklist = db.query(Checklist).filter(Checklist.id == checklist_id).one_or_none()
    if checklist is None:
        raise HTTPException(status_code=404, detail="Checklist not found")

    match = _get_or_create_match(db, checklist_id, photo_id)
    match.observation_id = body.observation_id
    match.fallback_common_name = None
    match.fallback_scientific_name = None
    match.fallback_species_code = None
    match.confidence = body.confidence
    match.method = "ai_suggested"
    match.reviewed_at = datetime.utcnow()

    if body.suggested_common_name is not None:
        _log_ai_suggestion(
            db,
            photo_id=photo_id,
            checklist_id=checklist_id,
            kind="constrained",
            suggested_common_name=body.suggested_common_name,
            confidence=body.confidence,
            outcome="accepted",
        )

    db.commit()
    db.refresh(match)

    # Match has no direct ORM relationship to Observation (only the
    # observation_id column) -- resolve it the same way outings.py does.
    # The accepted observation may belong to a sibling checklist in this
    # outing's group, not `checklist` itself, since suggest_species above
    # offers candidates from the whole group -- look it up there too.
    group = get_checklist_group(db, checklist)
    observation = next(
        (o for c in group for o in c.observations if o.id == match.observation_id), None
    )

    return {
        "checklist_id": checklist_id,
        "photo": photo_out(match.photo),
        "observation": observation,
        "method": match.method,
        "confidence": match.confidence,
        "ebird_checklist_url": ebird_checklist_url(checklist),
        "reviewed_at": match.reviewed_at.isoformat() if match.reviewed_at else None,
    }


@router.post("/{checklist_id}/reject/{photo_id}")
def reject_suggestion(
    checklist_id: int,
    photo_id: int,
    body: RejectSuggestionRequest,
    db: Session = Depends(get_db),
):
    """The user looked at a constrained SpeciesSuggestion and said no.
    Still writes nothing to Match -- there's nothing to undo, same as
    before this endpoint existed -- but now logs the rejection itself for
    AI accuracy tracking (see AiSuggestionLog)."""
    checklist = db.query(Checklist).filter(Checklist.id == checklist_id).one_or_none()
    if checklist is None:
        raise HTTPException(status_code=404, detail="Checklist not found")

    _log_ai_suggestion(
        db,
        photo_id=photo_id,
        checklist_id=checklist_id,
        kind="constrained",
        suggested_common_name=body.suggested_common_name,
        confidence=body.confidence,
        outcome="rejected",
    )
    db.commit()
    return {"status": "logged"}


@router.post("/{checklist_id}/assign/{photo_id}", response_model=MatchOut)
def assign_species(
    checklist_id: int,
    photo_id: int,
    body: AssignSpeciesRequest,
    db: Session = Depends(get_db),
):
    """Manually pick one of the outing's own reported species -- no AI
    suggestion behind it. For correcting a false-negative "no confident
    match" result (Strategy B is not perfectly accurate even in the easy
    case of a single candidate species)."""
    checklist = db.query(Checklist).filter(Checklist.id == checklist_id).one_or_none()
    if checklist is None:
        raise HTTPException(status_code=404, detail="Checklist not found")

    group = get_checklist_group(db, checklist)
    observation = next(
        (o for c in group for o in c.observations if o.id == body.observation_id), None
    )
    if observation is None:
        raise HTTPException(
            status_code=400, detail="That species isn't reported on this outing"
        )

    match = _get_or_create_match(db, checklist_id, photo_id)
    match.observation_id = body.observation_id
    # Clear any prior fallback label -- e.g. fixing a match that was
    # previously an "Other"/off-checklist guess to a real reported
    # species shouldn't leave the stale fallback fields behind.
    match.fallback_common_name = None
    match.fallback_scientific_name = None
    match.fallback_species_code = None
    match.confidence = 1.0
    match.method = "manual"
    match.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(match)

    return {
        "checklist_id": checklist_id,
        "photo": photo_out(match.photo),
        "observation": observation,
        "method": match.method,
        "confidence": match.confidence,
        "ebird_checklist_url": ebird_checklist_url(checklist),
        "reviewed_at": match.reviewed_at.isoformat() if match.reviewed_at else None,
    }




@router.post("/{checklist_id}/suggest-fallback/{photo_id}", response_model=FallbackSuggestion)
def suggest_fallback(checklist_id: int, photo_id: int, db: Session = Depends(get_db)):
    """Broader, unconstrained guess for a photo that doesn't match any of
    the outing's reported species -- see docs/USER_STORIES.md, "Species
    ID fallback for eBird gaps". Nothing persisted yet."""
    checklist = db.query(Checklist).filter(Checklist.id == checklist_id).one_or_none()
    if checklist is None:
        raise HTTPException(status_code=404, detail="Checklist not found")

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
        checklist_id=checklist_id,
        is_bird=result["is_bird"],
        common_name=common_name,
        scientific_name=scientific_name,
        species_code=species_code,
        confidence=result["confidence"],
        reasoning=result["reasoning"],
        ebird_checklist_url=ebird_checklist_url(checklist),
        is_other=is_other,
    )


class SuggestFallbackBatchRequest(BaseModel):
    photo_ids: list[int]


@router.post("/{checklist_id}/suggest-fallback-batch", response_model=list[FallbackSuggestion])
def suggest_fallback_batch(checklist_id: int, body: SuggestFallbackBatchRequest, db: Session = Depends(get_db)):
    """Batch version of suggest-fallback (issue #5) -- one Claude call for
    every checked photo instead of one round trip each. Same "nothing
    persisted yet" contract as the single-photo version; the caller
    still accepts each result individually via accept-fallback."""
    checklist = db.query(Checklist).filter(Checklist.id == checklist_id).one_or_none()
    if checklist is None:
        raise HTTPException(status_code=404, detail="Checklist not found")

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
                checklist_id=checklist_id,
                is_bird=r["is_bird"],
                common_name=common_name,
                scientific_name=scientific_name,
                species_code=species_code,
                confidence=r["confidence"],
                reasoning=r["reasoning"],
                ebird_checklist_url=ebird_checklist_url(checklist),
                is_other=is_other,
            )
        )
    return suggestions


@router.post("/{checklist_id}/accept-fallback/{photo_id}", response_model=MatchOut)
def accept_fallback(
    checklist_id: int,
    photo_id: int,
    body: AcceptFallbackRequest,
    db: Session = Depends(get_db),
):
    """A name was entered for this photo -- typed by hand, or accepted
    from an unconstrained AI guess. Either way, resolve it the same
    three ways rather than trusting where it came from (see
    conversation with Jen, 2026-08-04 -- this used to only check
    nothing, which meant a real off-checklist species and a genuine
    non-bird note were handled identically):

      1. Matches one of this outing's own reported species (any
         checklist in the group) -> a real, linked assignment, same as
         picking it from the dropdown directly.
      2. Not on this outing, but resolves against eBird's full
         taxonomy -> Off checklist: a real species, just not this one's,
         labels the photo only, never written back to eBird.
      3. Resolves as neither -> a plain Note. No signal it's a specific
         identifiable species, so a freeform label is the honest answer.
    """
    checklist = db.query(Checklist).filter(Checklist.id == checklist_id).one_or_none()
    if checklist is None:
        raise HTTPException(status_code=404, detail="Checklist not found")

    name = body.common_name.strip()
    group = get_checklist_group(db, checklist)

    on_checklist = next(
        (o for c in group for o in c.observations if o.common_name.lower() == name.lower()),
        None,
    )

    match = _get_or_create_match(db, checklist_id, photo_id)

    if on_checklist is not None:
        match.observation_id = on_checklist.id
        match.fallback_common_name = None
        match.fallback_scientific_name = None
        match.fallback_species_code = None
        match.confidence = 1.0
        match.method = "manual"
    else:
        match.observation_id = None
        resolved = find_species(name)
        if resolved:
            match.fallback_common_name = resolved["common_name"]
            match.fallback_scientific_name = resolved["scientific_name"]
            match.fallback_species_code = resolved["species_code"]
        else:
            match.fallback_common_name = name
            match.fallback_scientific_name = None
            match.fallback_species_code = None
        match.confidence = body.confidence
        match.method = "ai_fallback"

    match.reviewed_at = datetime.utcnow()

    if body.ai_suggested_common_name is not None:
        final_common_name = on_checklist.common_name if on_checklist is not None else match.fallback_common_name
        matches_suggestion = (
            final_common_name is not None
            and final_common_name.strip().lower() == body.ai_suggested_common_name.strip().lower()
        )
        _log_ai_suggestion(
            db,
            photo_id=photo_id,
            checklist_id=checklist_id,
            kind="unconstrained",
            suggested_common_name=body.ai_suggested_common_name,
            confidence=body.confidence,
            outcome="accepted" if matches_suggestion else "corrected",
            final_common_name=None if matches_suggestion else final_common_name,
        )

    db.commit()
    db.refresh(match)

    observation = None
    if match.observation_id:
        observation = next(
            (o for c in group for o in c.observations if o.id == match.observation_id), None
        )

    return {
        "checklist_id": checklist_id,
        "photo": photo_out(match.photo),
        "observation": observation,
        "method": match.method,
        "confidence": match.confidence,
        "fallback_common_name": match.fallback_common_name,
        "fallback_scientific_name": match.fallback_scientific_name,
        "ebird_checklist_url": ebird_checklist_url(checklist),
        "reviewed_at": match.reviewed_at.isoformat() if match.reviewed_at else None,
    }


@router.post("/{checklist_id}/adjust-timezone/{photo_id}")
def adjust_timezone(checklist_id: int, photo_id: int, db: Session = Depends(get_db)):
    """The user's response to a flagged timezone_mismatch (see
    app/services/timezone_check.py, issue #6): apply the camera-clock
    correction to this photo's `date_taken` and re-run matching. Deliberately
    doesn't return a MatchOut for this checklist_id specifically -- the
    correction can legitimately move the photo to a *different* checklist
    (that's the point), so the caller should refetch the outing rather
    than assume this photo stays put."""
    checklist = db.query(Checklist).filter(Checklist.id == checklist_id).one_or_none()
    if checklist is None:
        raise HTTPException(status_code=404, detail="Checklist not found")
    photo = db.query(Photo).filter(Photo.id == photo_id).one_or_none()
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    mismatch = check_mismatch(photo, checklist)
    if mismatch is None:
        raise HTTPException(status_code=400, detail="No timezone mismatch to adjust")

    corrected = datetime.fromisoformat(photo.date_taken) + timedelta(hours=mismatch["hours_diff"])
    photo.date_taken = corrected.strftime("%Y-%m-%d %H:%M:%S")
    photo.utc_offset = mismatch["expected_utc_offset"]
    db.commit()

    match_result = run_rule_based_matching(db)
    return {"date_taken": photo.date_taken, "match": match_result}

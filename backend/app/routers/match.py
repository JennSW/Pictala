"""Strategy B endpoints: AI-assisted species suggestions.

Two-step by design, matching DESIGN.md section 4's "show the guess, let the
user confirm/reject... never silently trusting it":

  POST /match/{checklist_id}/suggest/{photo_id}  -- ask the model, persist nothing
  POST /match/{checklist_id}/accept/{photo_id}   -- the user chose to keep it

There's no "/reject" endpoint on purpose: rejecting a suggestion just means
not calling accept -- nothing was ever written, so there's nothing to undo.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Checklist, Photo, Match
from app.schemas import SpeciesSuggestion, AcceptSuggestionRequest, MatchOut
from app.services.species_classifier import (
    guess_species,
    SpeciesClassifierNotConfigured,
    SpeciesClassifierError,
)

router = APIRouter(prefix="/match", tags=["match"])


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

    # De-dupe candidate species by common name (a checklist can have more
    # than one Observation row for the same species -- e.g. re-imports, or
    # multiple counts logged separately) while keeping the mapping back to
    # an observation_id for whichever one appears first.
    seen = {}
    for obs in checklist.observations:
        seen.setdefault(obs.common_name, obs.id)
    candidate_names = list(seen.keys())

    if not candidate_names:
        raise HTTPException(
            status_code=400, detail="This checklist has no species to suggest from"
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

    match = (
        db.query(Match)
        .filter(Match.checklist_id == checklist_id, Match.photo_id == photo_id)
        .one_or_none()
    )
    if match is None:
        # Shouldn't normally happen (the photo got here via rule-based
        # matching first), but don't silently no-op -- create the row so
        # accepting a suggestion always has a visible effect.
        match = Match(checklist_id=checklist_id, photo_id=photo_id)
        db.add(match)

    match.observation_id = body.observation_id
    match.confidence = body.confidence
    match.method = "ai_suggested"
    db.commit()
    db.refresh(match)

    # Match has no direct ORM relationship to Observation (only the
    # observation_id column) -- resolve it the same way outings.py does,
    # by looking it up in the checklist's own observations.
    observation = next(
        (o for o in checklist.observations if o.id == match.observation_id), None
    )

    return {
        "photo": match.photo,
        "observation": observation,
        "method": match.method,
        "confidence": match.confidence,
    }

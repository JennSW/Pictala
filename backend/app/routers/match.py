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

There's no "/reject" endpoint on purpose: rejecting a suggestion just means
not calling accept -- nothing was ever written, so there's nothing to undo.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Checklist, Photo, Match
from app.schemas import (
    SpeciesSuggestion,
    AcceptSuggestionRequest,
    AssignSpeciesRequest,
    FallbackSuggestion,
    AcceptFallbackRequest,
    MatchOut,
    photo_out,
    ebird_checklist_url,
)
from app.services.outing_grouping import get_checklist_group
from app.services.ebird_taxonomy import find_species
from app.services.species_classifier import (
    guess_species,
    guess_species_unconstrained,
    SpeciesClassifierNotConfigured,
    SpeciesClassifierError,
)

router = APIRouter(prefix="/match", tags=["match"])


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
    match.confidence = body.confidence
    match.method = "ai_suggested"
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
        "photo": photo_out(match.photo),
        "observation": observation,
        "method": match.method,
        "confidence": match.confidence,
        "ebird_checklist_url": ebird_checklist_url(checklist),
    }


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
    match.confidence = 1.0
    match.method = "manual"
    db.commit()
    db.refresh(match)

    return {
        "photo": photo_out(match.photo),
        "observation": observation,
        "method": match.method,
        "confidence": match.confidence,
        "ebird_checklist_url": ebird_checklist_url(checklist),
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

    species_code = scientific_name = None
    unresolved = False
    common_name = result["common_name"]
    if common_name:
        resolved = find_species(common_name)
        if resolved:
            common_name = resolved["common_name"]
            scientific_name = resolved["scientific_name"]
            species_code = resolved["species_code"]
        else:
            # The model named something eBird's taxonomy doesn't
            # recognize -- treat as unidentified rather than silently
            # accepting a name that isn't a real species, same
            # discipline as the constrained flow's candidate-list check.
            unresolved = True

    return FallbackSuggestion(
        photo_id=photo_id,
        checklist_id=checklist_id,
        is_bird=result["is_bird"],
        common_name=common_name if not unresolved else None,
        scientific_name=scientific_name,
        species_code=species_code,
        confidence=result["confidence"],
        reasoning=result["reasoning"],
        ebird_checklist_url=ebird_checklist_url(checklist),
        unresolved=unresolved,
    )


@router.post("/{checklist_id}/accept-fallback/{photo_id}", response_model=MatchOut)
def accept_fallback(
    checklist_id: int,
    photo_id: int,
    body: AcceptFallbackRequest,
    db: Session = Depends(get_db),
):
    """Keep a fallback identification. Photo-level only: this never
    creates or alters an Observation, never touches the checklist's own
    species list, and never writes back to eBird -- see
    docs/USER_STORIES.md, "Species ID fallback for eBird gaps"."""
    checklist = db.query(Checklist).filter(Checklist.id == checklist_id).one_or_none()
    if checklist is None:
        raise HTTPException(status_code=404, detail="Checklist not found")

    match = _get_or_create_match(db, checklist_id, photo_id)
    match.observation_id = None
    match.fallback_common_name = body.common_name
    match.fallback_scientific_name = body.scientific_name
    match.fallback_species_code = body.species_code
    match.confidence = body.confidence
    match.method = "ai_fallback"
    db.commit()
    db.refresh(match)

    return {
        "photo": photo_out(match.photo),
        "observation": None,
        "method": match.method,
        "confidence": match.confidence,
        "fallback_common_name": match.fallback_common_name,
        "fallback_scientific_name": match.fallback_scientific_name,
        "ebird_checklist_url": ebird_checklist_url(checklist),
    }

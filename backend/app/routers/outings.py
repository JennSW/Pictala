from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Checklist
from app.schemas import OutingSummary, OutingDetail, photo_out, ebird_checklist_url
from app.services.outing_grouping import group_checklists, get_checklist_group


def _is_resolved(match) -> bool:
    """A match is "resolved" once it has a real species attached, either
    a reported observation or an approved fallback identification --
    either way, it should win over an unresolved duplicate of the same
    photo from a sibling checklist in the group."""
    return match.observation_id is not None or match.fallback_common_name is not None

router = APIRouter(prefix="/outings", tags=["outings"])


@router.get("", response_model=list[OutingSummary])
def list_outings(db: Session = Depends(get_db)):
    checklists = db.query(Checklist).order_by(Checklist.date.desc()).all()
    summaries = []
    for group in group_checklists(checklists):
        # Canonical id for a group is its lowest checklist id -- stable,
        # and lets /outings/{id} be looked up with any member's id (see
        # get_outing) without changing the route's shape.
        primary = min(group, key=lambda c: c.id)
        species = {obs.common_name for c in group for obs in c.observations}
        photo_ids = {m.photo_id for c in group for m in c.matches}
        summaries.append(
            OutingSummary(
                id=primary.id,
                location_name=primary.location_name,
                date=primary.date,
                species_count=len(species),
                photo_count=len(photo_ids),
            )
        )
    summaries.sort(key=lambda s: s.date, reverse=True)
    return summaries


@router.get("/{outing_id}", response_model=OutingDetail)
def get_outing(outing_id: int, db: Session = Depends(get_db)):
    checklist = db.query(Checklist).filter(Checklist.id == outing_id).one_or_none()
    if checklist is None:
        raise HTTPException(status_code=404, detail="Outing not found")

    group = get_checklist_group(db, checklist)
    all_observations = [obs for c in group for obs in c.observations]
    all_matches = [m for c in group for m in c.matches]

    # Independent per-checklist matching (matcher.py) can give the same
    # photo its own Match row under each checklist in the group -- e.g.
    # a Tufted Puffin photo confirmed under the "Tufted Puffin" checklist
    # and also showing as an unresolved candidate under three sibling
    # checklists at the same location/date. Dedupe by photo, preferring
    # a confirmed match over an unconfirmed duplicate for the same photo.
    matches_by_photo = {}
    for m in all_matches:
        current = matches_by_photo.get(m.photo_id)
        if current is None or (not _is_resolved(current) and _is_resolved(m)):
            matches_by_photo[m.photo_id] = m

    return OutingDetail(
        id=checklist.id,
        location_name=checklist.location_name,
        date=checklist.date,
        latitude=checklist.latitude,
        longitude=checklist.longitude,
        observations=all_observations,
        matches=[
            {
                "photo": photo_out(m.photo),
                "observation": next(
                    (o for o in all_observations if o.id == m.observation_id), None
                ),
                "method": m.method,
                "confidence": m.confidence,
                "fallback_common_name": m.fallback_common_name,
                "fallback_scientific_name": m.fallback_scientific_name,
                "ebird_checklist_url": ebird_checklist_url(m.checklist),
            }
            for m in matches_by_photo.values()
        ],
    )

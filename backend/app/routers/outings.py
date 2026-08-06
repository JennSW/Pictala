from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Checklist, Photo
from app.schemas import OutingSummary, OutingDetail, photo_out, ebird_checklist_url
from app.services.outing_grouping import group_checklists, get_checklist_group
from app.services.timezone_check import check_mismatch
from app.services.duplicate_detection import find_duplicate_groups
from app.services.outing_review import compute_photo_groups


def _is_resolved(match) -> bool:
    """A match is "resolved" once it has a real species attached, either
    a reported observation or an approved fallback identification --
    either way, it should win over an unresolved duplicate of the same
    photo from a sibling checklist in the group."""
    return match.observation_id is not None or match.fallback_common_name is not None


def _possible_duplicate(db: Session, groups: dict[int, list[int]], photo: Photo) -> dict | None:
    other_ids = groups.get(photo.id)
    if not other_ids:
        return None
    others = db.query(Photo).filter(Photo.id.in_(other_ids)).all()
    return {
        "other_photo_ids": other_ids,
        "other_flickr_urls": [photo_out(o).flickr_url for o in others],
    }


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
                reviewed_at=primary.outing_reviewed_at.isoformat() if primary.outing_reviewed_at else None,
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

    duplicate_groups = find_duplicate_groups(db)
    primary = min(group, key=lambda c: c.id)

    return OutingDetail(
        id=checklist.id,
        location_name=checklist.location_name,
        date=checklist.date,
        latitude=checklist.latitude,
        longitude=checklist.longitude,
        observations=all_observations,
        reviewed_at=primary.outing_reviewed_at.isoformat() if primary.outing_reviewed_at else None,
        photo_groups=compute_photo_groups(list(matches_by_photo.values()), all_observations),
        matches=[
            {
                "checklist_id": m.checklist_id,
                "photo": photo_out(m.photo),
                "observation": next(
                    (o for o in all_observations if o.id == m.observation_id), None
                ),
                "method": m.method,
                "confidence": m.confidence,
                "fallback_common_name": m.fallback_common_name,
                "fallback_scientific_name": m.fallback_scientific_name,
                "ebird_checklist_url": ebird_checklist_url(m.checklist),
                "reviewed_at": m.reviewed_at.isoformat() if m.reviewed_at else None,
                "timezone_mismatch": check_mismatch(m.photo, m.checklist),
                "possible_duplicate": _possible_duplicate(db, duplicate_groups, m.photo),
            }
            for m in matches_by_photo.values()
        ],
    )


def _resolve_primary(db: Session, outing_id: int) -> Checklist:
    checklist = db.query(Checklist).filter(Checklist.id == outing_id).one_or_none()
    if checklist is None:
        raise HTTPException(status_code=404, detail="Outing not found")
    group = get_checklist_group(db, checklist)
    return min(group, key=lambda c: c.id)


@router.post("/{outing_id}/mark-reviewed")
def mark_reviewed(outing_id: int, db: Session = Depends(get_db)):
    """Explicit, stored "this outing has been reviewed" state (issue
    #43) -- deliberately not computed live from whether any photos
    still need review, since this is likely to anchor a future feature
    (the saved/locked-day concept from #11)."""
    primary = _resolve_primary(db, outing_id)
    primary.outing_reviewed_at = datetime.utcnow()
    db.commit()
    return {"reviewed_at": primary.outing_reviewed_at.isoformat()}


@router.post("/{outing_id}/unmark-reviewed")
def unmark_reviewed(outing_id: int, db: Session = Depends(get_db)):
    primary = _resolve_primary(db, outing_id)
    primary.outing_reviewed_at = None
    db.commit()
    return {"reviewed_at": None}

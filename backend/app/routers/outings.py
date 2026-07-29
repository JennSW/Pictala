from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Checklist, Match
from app.schemas import OutingSummary, OutingDetail, photo_out

router = APIRouter(prefix="/outings", tags=["outings"])


@router.get("", response_model=list[OutingSummary])
def list_outings(db: Session = Depends(get_db)):
    checklists = db.query(Checklist).order_by(Checklist.date.desc()).all()
    return [
        OutingSummary(
            id=c.id,
            location_name=c.location_name,
            date=c.date,
            species_count=len(c.observations),
            photo_count=len({m.photo_id for m in c.matches}),
        )
        for c in checklists
    ]


@router.get("/{outing_id}", response_model=OutingDetail)
def get_outing(outing_id: int, db: Session = Depends(get_db)):
    checklist = db.query(Checklist).filter(Checklist.id == outing_id).one_or_none()
    if checklist is None:
        raise HTTPException(status_code=404, detail="Outing not found")
    return OutingDetail(
        id=checklist.id,
        location_name=checklist.location_name,
        date=checklist.date,
        latitude=checklist.latitude,
        longitude=checklist.longitude,
        observations=checklist.observations,
        matches=[
            {
                "photo": photo_out(m.photo),
                "observation": next(
                    (o for o in checklist.observations if o.id == m.observation_id), None
                ),
                "method": m.method,
                "confidence": m.confidence,
            }
            for m in checklist.matches
        ],
    )

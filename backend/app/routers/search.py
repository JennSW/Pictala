"""GET /search -- species search across confirmed matches only.

See docs/USER_STORIES.md, "Story: Search by species". Reuses existing
data (no new matching logic or external calls). Joining through
Observation naturally scopes results to confirmed matches (Bucket 1):
Match.observation_id is nullable, so an inner join drops any match with
no confirmed species -- unmatched/pending photos are never surfaced here.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Checklist, Match, Observation
from app.schemas import SearchResult, photo_out

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=list[SearchResult])
def search_by_species(
    species: str = Query(
        ..., min_length=1, description="Common name, partial match, case-insensitive"
    ),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Match, Observation, Checklist)
        .join(Observation, Match.observation_id == Observation.id)
        .join(Checklist, Match.checklist_id == Checklist.id)
        .filter(Observation.common_name.ilike(f"%{species}%"))
        .order_by(Checklist.date.desc())
        .all()
    )
    return [
        SearchResult(
            checklist_id=checklist.id,
            location_name=checklist.location_name,
            date=checklist.date,
            common_name=observation.common_name,
            photo=photo_out(match.photo),
        )
        for match, observation, checklist in rows
    ]

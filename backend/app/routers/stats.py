"""Aggregate stats over AiSuggestionLog -- currently just AI accuracy
(2026-09-03), a real, honest number for how often Claude's species
suggestions turned out right, split by suggestion kind since the
constrained and unconstrained flows have meaningfully different
difficulty (see AiSuggestionLog's docstring)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AiSuggestionLog
from app.schemas import AiAccuracyBucket, AiAccuracyStats

router = APIRouter(prefix="/stats", tags=["stats"])


def _bucket(rows: list[AiSuggestionLog]) -> AiAccuracyBucket:
    total = len(rows)
    accepted = sum(1 for r in rows if r.outcome == "accepted")
    corrected = sum(1 for r in rows if r.outcome == "corrected")
    rejected = sum(1 for r in rows if r.outcome == "rejected")
    return AiAccuracyBucket(
        total=total,
        accepted=accepted,
        corrected=corrected,
        rejected=rejected,
        accuracy=(accepted / total) if total else None,
    )


@router.get("/ai-accuracy", response_model=AiAccuracyStats)
def ai_accuracy(db: Session = Depends(get_db)):
    rows = db.query(AiSuggestionLog).all()
    overall = _bucket(rows)
    kinds = sorted({r.kind for r in rows})
    by_kind = {kind: _bucket([r for r in rows if r.kind == kind]) for kind in kinds}
    return AiAccuracyStats(**overall.model_dump(), by_kind=by_kind)

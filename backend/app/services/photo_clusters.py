"""Checklist-less photo clusters (issue #35).

Some photos have no eBird checklist to attach to -- either permanently
(a captive/indoor bird photo, never a countable eBird sighting) or just
not yet (a real outing whose checklist hasn't been uploaded). See
models.py's Match.checklist_id docstring for why that's represented as
null rather than a sentinel id.

Clusters are computed on the fly here, not stored: photos with no Match
row tied to a real checklist are grouped by date, then split into
sub-clusters whenever there's more than CLUSTER_GAP between two
consecutive photos. This stands in for "grouped by date + GPS
proximity" from the original 2026-07-28 design -- GPS is essentially
never present on real photos (see issue #8/#9), so capture-time
proximity is the only signal actually available.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Match, Photo
from app.services.photo_dates import effective_datetime

CLUSTER_GAP = timedelta(minutes=60)


def _orphan_photos(db: Session) -> list[Photo]:
    """Photos with no Match row tied to a real checklist -- either no
    Match row at all, or only a checklist-less (checklist_id IS NULL)
    one, i.e. already identified once but still homeless."""
    claimed_photo_ids = {
        m.photo_id for m in db.query(Match).filter(Match.checklist_id.isnot(None)).all()
    }
    orphans = []
    for photo in db.query(Photo).all():
        if photo.id in claimed_photo_ids or not photo.date_taken:
            continue
        try:
            datetime.fromisoformat(photo.date_taken)
        except ValueError:
            continue
        orphans.append(photo)
    return orphans


def compute_clusters(db: Session) -> list[dict]:
    """Returns clusters newest-first: [{id, date, photo_ids}]. `id` is a
    stable synthetic string (date + index within that date) -- there's
    nothing to store, the grouping is recomputed each call from whatever
    is currently orphaned."""
    orphans = _orphan_photos(db)
    parsed = sorted(
        ((p, effective_datetime(p)) for p in orphans),
        key=lambda pair: pair[1],
    )

    clusters: list[list[tuple[Photo, datetime]]] = []
    for photo, taken in parsed:
        if clusters:
            _, prev_taken = clusters[-1][-1]
            same_day = prev_taken.date() == taken.date()
            close_enough = (taken - prev_taken) <= CLUSTER_GAP
            if same_day and close_enough:
                clusters[-1].append((photo, taken))
                continue
        clusters.append([(photo, taken)])

    result = []
    per_date_index: dict[str, int] = {}
    for cluster in clusters:
        date = cluster[0][1].date().isoformat()
        idx = per_date_index.get(date, 0)
        per_date_index[date] = idx + 1
        result.append(
            {
                "id": f"{date}-{idx}",
                "date": date,
                "photo_ids": [p.id for p, _ in cluster],
            }
        )
    result.sort(key=lambda c: c["date"], reverse=True)
    return result


def get_cluster(db: Session, cluster_id: str) -> dict | None:
    for cluster in compute_clusters(db):
        if cluster["id"] == cluster_id:
            return cluster
    return None

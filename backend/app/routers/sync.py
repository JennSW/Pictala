"""Endpoints that trigger data ingestion + matching.

These are POST endpoints you'd click from a "sync" button in the UI (or hit
via curl / the auto-generated /docs page during a demo) -- not things that
run on a schedule, since this is a single-user local tool, not a service.
"""
import tempfile
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.ebird_import import import_ebird_csv
from app.services.flickr_client import get_photos_in_range
from app.services.flickr_exif import get_utc_offset
from app.services.matcher import run_rule_based_matching
from app.services.duplicate_detection import recompute_and_store
from app.models import Photo, SyncLog

router = APIRouter(prefix="/sync", tags=["sync"])

# Manual "Sync now" cap from docs/USER_STORIES.md's Sync spec -- 4/day,
# independent of the (not-yet-built) automatic-sync budget.
DAILY_SYNC_LIMIT = 4


def _syncs_used_today(db: Session) -> int:
    today_start = datetime.combine(date.today(), datetime.min.time())
    return (
        db.query(SyncLog)
        .filter(SyncLog.triggered_at >= today_start)
        .count()
    )


@router.post("/ebird")
async def sync_ebird(db: Session = Depends(get_db), file: UploadFile = File(...)):
    """Upload your eBird 'Download My Data' CSV export."""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    return import_ebird_csv(db, tmp_path, original_filename=file.filename)


def _parse_flickr_coord(raw) -> float | None:
    """Flickr returns a lat/lon of "0" (or "0.000000") for photos with no
    location tagged -- it's a sentinel, not a real coordinate (it lands in
    the ocean off the coast of Africa). Parse defensively and treat a
    (0, 0) pair as "no GPS data" rather than a real match candidate."""
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


@router.post("/flickr")
def sync_flickr(min_taken_date: str, max_taken_date: str, db: Session = Depends(get_db)):
    """Pull Flickr photos in a date range (YYYY-MM-DD) and upsert them --
    refreshes title/tags/coordinates/url on photos already synced, not
    just inserting new ones. Editing tags on Flickr after the fact (e.g.
    to help species matching) needs to actually reach the app; a
    photo that already exists used to be skipped entirely, so no amount
    of re-syncing ever picked up such edits."""
    raw_photos = get_photos_in_range(min_taken_date, max_taken_date)
    created = 0
    updated = 0
    for p in raw_photos:
        lat = _parse_flickr_coord(p.get("latitude"))
        lon = _parse_flickr_coord(p.get("longitude"))
        if lat == 0.0 and lon == 0.0:
            lat, lon = None, None

        existing = db.query(Photo).filter(Photo.flickr_id == p["id"]).one_or_none()
        if existing:
            existing.title = p.get("title")
            existing.tags = p.get("tags")
            existing.latitude = lat
            existing.longitude = lon
            existing.url_medium = p.get("url_m")
            if existing.utc_offset is None:
                existing.utc_offset = _try_get_utc_offset(p["id"])
            updated += 1
            continue

        db.add(
            Photo(
                flickr_id=p["id"],
                title=p.get("title"),
                tags=p.get("tags"),
                date_taken=p.get("datetaken", ""),
                latitude=lat,
                longitude=lon,
                url_medium=p.get("url_m"),
                utc_offset=_try_get_utc_offset(p["id"]),
            )
        )
        created += 1
    db.commit()

    # Recompute duplicate flags here, at write time, once -- not on every
    # outing/cluster page load. Only worth it if titles/data actually
    # changed (a title edit on Flickr is the only thing that can move a
    # photo in or out of a duplicate group).
    if created or updated:
        recompute_and_store(db)

    return {"photos_created": created, "photos_updated": updated}


def _try_get_utc_offset(flickr_id: str) -> str | None:
    """A separate API call per photo (see flickr_exif.py) -- only worth
    doing for photos that don't have it cached yet (see call sites), and
    shouldn't take down the whole sync if Flickr hiccups on one photo or
    the tag just isn't there."""
    try:
        return get_utc_offset(flickr_id)
    except Exception:
        return None


@router.post("/match")
def sync_match(db: Session = Depends(get_db)):
    """Re-run rule-based matching over everything currently in the DB."""
    return run_rule_based_matching(db)


@router.get("/status")
def sync_status(db: Session = Depends(get_db)):
    """Powers the Sync button's remaining-count display and last-sync-time
    label."""
    used = _syncs_used_today(db)
    last = db.query(SyncLog).order_by(SyncLog.triggered_at.desc()).first()
    return {
        "used": used,
        "limit": DAILY_SYNC_LIMIT,
        "remaining": max(0, DAILY_SYNC_LIMIT - used),
        "last_synced_at": last.triggered_at.isoformat() if last else None,
    }


@router.post("/run")
def sync_run(
    min_taken_date: str | None = None,
    max_taken_date: str | None = None,
    db: Session = Depends(get_db),
):
    """The "Sync now" button (docs/USER_STORIES.md, "Story: Manual
    sync") -- pulls fresh Flickr photos and re-runs matching, capped at
    DAILY_SYNC_LIMIT/day (resets at local midnight, per the spec's
    "calendar day in the user's own time zone" rule -- see SyncLog's
    `triggered_at`). Every attempt counts toward the cap regardless of
    outcome, so the SyncLog row is written before the actual work runs.

    No last-successful-sync tracking exists yet to compute a tight
    "just the new stuff" window, so this defaults to a 30-day lookback
    through today when no explicit range is given -- the underlying
    Flickr sync already upserts safely, so re-covering recently-synced
    days is harmless, just not free."""
    used = _syncs_used_today(db)
    if used >= DAILY_SYNC_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Daily sync limit ({DAILY_SYNC_LIMIT}) already reached today.",
        )

    db.add(SyncLog())
    db.commit()

    today = date.today()
    if max_taken_date is None:
        max_taken_date = today.isoformat()
    if min_taken_date is None:
        min_taken_date = (today - timedelta(days=30)).isoformat()

    flickr_result = sync_flickr(min_taken_date, max_taken_date, db)
    match_result = sync_match(db)

    return {
        "flickr": flickr_result,
        "match": match_result,
        "remaining": max(0, DAILY_SYNC_LIMIT - used - 1),
    }

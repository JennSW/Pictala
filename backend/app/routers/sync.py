"""Endpoints that trigger data ingestion + matching.

These are POST endpoints you'd click from a "sync" button in the UI (or hit
via curl / the auto-generated /docs page during a demo) -- not things that
run on a schedule, since this is a single-user local tool, not a service.
"""
import tempfile

from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.ebird_import import import_ebird_csv
from app.services.flickr_client import get_photos_in_range
from app.services.matcher import run_rule_based_matching
from app.models import Photo

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/ebird")
async def sync_ebird(db: Session = Depends(get_db), file: UploadFile = File(...)):
    """Upload your eBird 'Download My Data' CSV export."""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    return import_ebird_csv(db, tmp_path)


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
    """Pull Flickr photos in a date range (YYYY-MM-DD) and upsert them."""
    raw_photos = get_photos_in_range(min_taken_date, max_taken_date)
    created = 0
    for p in raw_photos:
        existing = db.query(Photo).filter(Photo.flickr_id == p["id"]).one_or_none()
        if existing:
            continue

        lat = _parse_flickr_coord(p.get("latitude"))
        lon = _parse_flickr_coord(p.get("longitude"))
        if lat == 0.0 and lon == 0.0:
            lat, lon = None, None

        db.add(
            Photo(
                flickr_id=p["id"],
                title=p.get("title"),
                tags=p.get("tags"),
                date_taken=p.get("datetaken", ""),
                latitude=lat,
                longitude=lon,
                url_medium=p.get("url_m"),
            )
        )
        created += 1
    db.commit()
    return {"photos_created": created}


@router.post("/match")
def sync_match(db: Session = Depends(get_db)):
    """Re-run rule-based matching over everything currently in the DB."""
    return run_rule_based_matching(db)

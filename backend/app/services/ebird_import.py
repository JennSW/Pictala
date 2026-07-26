"""Import an eBird "Download My Data" CSV export into the local DB.

Why a CSV importer instead of hitting the live API for personal history:
see DESIGN.md section 7. The live eBird API (api.ebird.org/v2) is built for
*regional* queries (recent observations in a region, checklist feeds for a
region+date) -- there is no simple "give me all of my own checklists ever"
endpoint. eBird's own export (My eBird -> Download My Data) is the
practical source for a personal history, so that's what this app ingests.

Expected columns (eBird's export header, as of this writing):
Submission ID, Common Name, Scientific Name, Taxonomic Order, Count,
State/Province, County, Location ID, Location, Latitude, Longitude, Date,
Time, Protocol, Duration (Min), All Obs Reported, Distance Traveled (km),
Area Covered (ha), Number of Observers, Breeding Code, Observation Details,
Checklist Comments, ML Catalog Numbers

The importer is deliberately tolerant of missing/renamed columns (eBird has
changed export headers before) -- it looks columns up by best-effort match
rather than fixed position.
"""
import csv
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Checklist, Match, Observation


def _get(row: dict, *candidates: str) -> str | None:
    """Return the first present, non-empty value among candidate column
    names, case-insensitively. eBird exports use spaces/slashes that vary
    slightly across export versions."""
    lower_row = {k.strip().lower(): v for k, v in row.items()}
    for c in candidates:
        v = lower_row.get(c.lower())
        if v not in (None, ""):
            return v
    return None


def import_ebird_csv(db: Session, csv_path: str) -> dict:
    created_checklists = 0
    created_observations = 0
    skipped = 0
    # Checklists we've already reset in *this* import call, so a checklist
    # spanning multiple CSV rows only gets cleared once, not once per row.
    reimported_checklist_ids: set[int] = set()

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            submission_id = _get(row, "Submission ID", "submission_id")
            if not submission_id:
                skipped += 1
                continue

            checklist = (
                db.query(Checklist)
                .filter(Checklist.submission_id == submission_id)
                .one_or_none()
            )
            if checklist is None:
                date_raw = _get(row, "Date")
                date_iso = _normalize_date(date_raw) if date_raw else ""
                lat = _get(row, "Latitude")
                lon = _get(row, "Longitude")
                duration = _get(row, "Duration (Min)", "Duration(Min)")

                checklist = Checklist(
                    submission_id=submission_id,
                    location_name=_get(row, "Location") or "Unknown location",
                    latitude=float(lat) if lat else None,
                    longitude=float(lon) if lon else None,
                    date=date_iso,
                    start_time=_get(row, "Time"),
                    duration_minutes=float(duration) if duration else None,
                )
                db.add(checklist)
                db.flush()  # get checklist.id
                created_checklists += 1
            elif checklist.id not in reimported_checklist_ids:
                # Re-uploading a CSV that's already been imported (common
                # during a demo/testing loop) used to append duplicate
                # species rows on every run. Clear stale observations and
                # any matches pointing at them before re-adding this
                # checklist's rows fresh -- mirrors the idempotent rebuild
                # matcher.py already does for matches.
                db.query(Match).filter(Match.checklist_id == checklist.id).update(
                    {Match.observation_id: None}
                )
                db.query(Observation).filter(
                    Observation.checklist_id == checklist.id
                ).delete()
                reimported_checklist_ids.add(checklist.id)

            db.add(
                Observation(
                    checklist_id=checklist.id,
                    common_name=_get(row, "Common Name") or "Unknown species",
                    scientific_name=_get(row, "Scientific Name"),
                    count=_get(row, "Count"),
                )
            )
            created_observations += 1

    db.commit()
    return {
        "checklists_created": created_checklists,
        "observations_created": created_observations,
        "rows_skipped": skipped,
    }


def _normalize_date(date_raw: str) -> str:
    """eBird exports dates like '14 Jun 2026' -- normalize to ISO 8601."""
    for fmt in ("%d %b %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_raw, fmt).date().isoformat()
        except ValueError:
            continue
    return date_raw  # fall back to whatever eBird gave us

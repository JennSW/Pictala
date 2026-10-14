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

Also accepts eBird's other CSV export -- the single-checklist "Download"
button on an individual checklist page (filename like
S123456789_observations.csv). That format has no Submission ID column at
all (every row already belongs to the one checklist named in the file),
uses different column names (Species, Observation Date, Start Time), and
a free-text duration ("1 hour(s), 53 minute(s)") instead of a plain number
of minutes -- handled below rather than asking the user to re-export in
the other format.
"""
import csv
import io
import re
import zipfile
from datetime import datetime

from sqlalchemy.orm import Session

from app.errors import BadInputError
from app.models import Checklist, Match, Observation

_CHECKLIST_ID_RE = re.compile(r"(S\d+)")


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


MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # far larger than any real eBird export

_WHERE_TO_GET_IT = (
    "In eBird choose My eBird > Download My Data (https://ebird.org/downloadMyData); eBird emails "
    "it to you. Or open a single checklist and use its Download button. Then upload that file."
)


def extract_csv_from_upload(raw: bytes, filename: str | None) -> tuple[bytes, str | None]:
    """The bytes of the CSV inside an upload, plus its name.

    eBird emails "Download My Data" as a .zip holding the CSV, so people reasonably
    upload the zip. Unpack it for them instead of failing."""
    if not raw:
        raise BadInputError("That file is empty.", _WHERE_TO_GET_IT)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise BadInputError(
            "That file is larger than 50 MB, far bigger than any eBird export.",
            "Check you chose the right file. " + _WHERE_TO_GET_IT,
        )
    if not raw.startswith(b"PK"):  # not a zip: assume it is the CSV itself
        return raw, filename
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            members = [
                i for i in zf.infolist()
                if i.filename.lower().endswith(".csv")
                and not i.is_dir()
                and "__MACOSX" not in i.filename
            ]
            if not members:
                raise BadInputError(
                    "That zip file doesn't contain a CSV.",
                    "eBird's download is a zip holding a file called MyEBirdData.csv. " + _WHERE_TO_GET_IT,
                )
            member = members[0]
            if member.file_size > MAX_UPLOAD_BYTES:
                raise BadInputError("The CSV inside that zip is larger than 50 MB.", _WHERE_TO_GET_IT)
            return zf.read(member), member.filename.rsplit("/", 1)[-1]
    except zipfile.BadZipFile as exc:
        raise BadInputError(
            "That file looks like a zip but couldn't be opened.",
            "It may have been cut short while downloading. Download it again, or unzip it yourself "
            "and upload the CSV inside.",
        ) from exc


def _to_float(raw: str | None) -> float | None:
    """A number, or None when the cell is blank or not a number (one odd row must not
    sink a whole import)."""
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def import_ebird_csv(db: Session, csv_path: str, original_filename: str | None = None) -> dict:
    created_checklists = 0
    created_observations = 0
    skipped = 0
    # Checklists we've already handled in *this* import call (reset if they
    # pre-existed, or freshly created), so a checklist spanning multiple CSV
    # rows is only touched once, not once per row.
    reimported_checklist_ids: set[int] = set()
    # For checklists that already existed: which species each confirmed
    # match pointed at before we rebuild the rows, as
    # {checklist_id: [(match, common_name, scientific_name), ...]}, so the
    # links can be restored afterward (issue #95).
    relink_plan: dict[int, list[tuple[Match, str, str | None]]] = {}

    try:
        # utf-8-sig: spreadsheet programs add an invisible byte-order mark that would
        # otherwise glue itself onto the first column name and hide every checklist.
        with open(csv_path, "rb") as fh:
            text = fh.read().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BadInputError(
            "That file couldn't be read as a text CSV.",
            "It may be a different kind of file, or a spreadsheet saved in another format. "
            + _WHERE_TO_GET_IT,
        ) from exc

    with io.StringIO(text, newline="") as f:
        reader = csv.DictReader(f)
        columns = {c.strip().lower() for c in (reader.fieldnames or [])}
        if not columns:
            raise BadInputError("That file is empty.", _WHERE_TO_GET_IT)
        if not columns & {"common name", "species"}:
            raise BadInputError(
                "That doesn't look like an eBird export: it has no species column.",
                "An eBird export has columns such as 'Submission ID' and 'Common Name'. "
                + _WHERE_TO_GET_IT,
            )

        # Single-checklist exports have no Submission ID column -- derive
        # one from the filename (eBird names these S<digits>_observations.csv)
        # and share it across every row, since they all belong to that one
        # checklist.
        has_submission_id_column = reader.fieldnames and any(
            fn.strip().lower() == "submission id" for fn in reader.fieldnames
        )
        fallback_submission_id = None
        if not has_submission_id_column:
            m = _CHECKLIST_ID_RE.search(original_filename or csv_path)
            if m:
                fallback_submission_id = m.group(1)

        for row in reader:
            submission_id = _get(row, "Submission ID", "submission_id") or fallback_submission_id
            if not submission_id:
                skipped += 1
                continue

            checklist = (
                db.query(Checklist)
                .filter(Checklist.submission_id == submission_id)
                .one_or_none()
            )
            if checklist is None:
                date_raw = _get(row, "Date", "Observation Date")
                date_iso = _normalize_date(date_raw) if date_raw else ""
                lat = _to_float(_get(row, "Latitude"))
                lon = _to_float(_get(row, "Longitude"))
                duration_raw = _get(row, "Duration (Min)", "Duration(Min)", "Duration")

                checklist = Checklist(
                    submission_id=submission_id,
                    location_name=_get(row, "Location") or "Unknown location",
                    location_id=_get(row, "Location ID"),
                    latitude=lat,
                    longitude=lon,
                    date=date_iso,
                    start_time=_get(row, "Time", "Start Time"),
                    duration_minutes=_parse_duration_minutes(duration_raw),
                )
                db.add(checklist)
                db.flush()  # get checklist.id
                created_checklists += 1
                # Mark it handled now: without this, this checklist's *second*
                # CSV row finds it already in the DB and takes the re-import
                # branch below, deleting the first row's observation.
                reimported_checklist_ids.add(checklist.id)
            elif checklist.id not in reimported_checklist_ids:
                # Re-uploading a CSV that's already been imported (and
                # eBird's export is cumulative, so every upload does this)
                # used to append duplicate species rows on every run. Clear
                # stale observations before re-adding this checklist's rows
                # fresh -- mirrors the idempotent rebuild matcher.py already
                # does for matches.
                #
                # Observation ids change on rebuild, so remember which
                # species each linked match pointed at and restore the link
                # once the new rows exist (below). Just nulling the links
                # silently reverted confirmed matches to "Unmatched" (#95).
                linked = (
                    db.query(Match, Observation)
                    .join(Observation, Match.observation_id == Observation.id)
                    .filter(Match.checklist_id == checklist.id)
                    .all()
                )
                relink_plan[checklist.id] = [
                    (m, o.common_name, o.scientific_name) for m, o in linked
                ]
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
                    common_name=_get(row, "Common Name", "Species") or "Unknown species",
                    scientific_name=_get(row, "Scientific Name"),
                    count=_get(row, "Count"),
                )
            )
            created_observations += 1

    relinked, unlinked = _relink_matches(db, relink_plan)
    db.commit()
    return {
        "checklists_created": created_checklists,
        "observations_created": created_observations,
        "rows_skipped": skipped,
        "matches_relinked": relinked,
        "matches_unlinked": unlinked,
    }


def _relink_matches(
    db: Session, relink_plan: dict[int, list[tuple[Match, str, str | None]]]
) -> tuple[int, int]:
    """Point each match back at the rebuilt Observation for the same species.

    Matches by scientific name first (stable across eBird's occasional
    common-name changes), then common name. A species that's no longer on
    the checklist -- the person edited it on eBird -- has nothing valid to
    link to, so it stays unlinked and is counted so the caller can say so
    rather than losing it silently. Returns (relinked, unlinked).
    """
    db.flush()  # assign ids to the freshly added Observation rows
    relinked = unlinked = 0
    for checklist_id, entries in relink_plan.items():
        rebuilt = db.query(Observation).filter(Observation.checklist_id == checklist_id).all()
        by_scientific = {o.scientific_name.lower(): o for o in reversed(rebuilt) if o.scientific_name}
        by_common = {o.common_name.lower(): o for o in reversed(rebuilt)}
        for match, common_name, scientific_name in entries:
            target = (scientific_name and by_scientific.get(scientific_name.lower())) or by_common.get(
                common_name.lower()
            )
            if target is None:
                unlinked += 1
                continue
            match.observation_id = target.id
            relinked += 1
    return relinked, unlinked


def _normalize_date(date_raw: str) -> str:
    """eBird exports dates like '14 Jun 2026' (history export) or
    'Aug 7, 2026' (single-checklist export) -- normalize to ISO 8601."""
    for fmt in ("%d %b %Y", "%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_raw, fmt).date().isoformat()
        except ValueError:
            continue
    return date_raw  # fall back to whatever eBird gave us


_DURATION_TEXT_RE = re.compile(
    r"(?:(?P<hours>\d+)\s*hour\(s\))?,?\s*(?:(?P<minutes>\d+)\s*minute\(s\))?"
)


def _parse_duration_minutes(raw: str | None) -> float | None:
    """The history export gives a plain number of minutes ("113"); the
    single-checklist export gives free text ("1 hour(s), 53 minute(s)") --
    parse either."""
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    m = _DURATION_TEXT_RE.search(raw)
    if not m or not (m.group("hours") or m.group("minutes")):
        return None
    return float(int(m.group("hours") or 0) * 60 + int(m.group("minutes") or 0))

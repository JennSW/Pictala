"""Work out which calendar day a photo was really taken on (issue #34).

Flickr's `date_taken` comes from the photo's EXIF metadata. When a photo
has none (scans, exports, edited copies), Flickr falls back to the upload
time -- so the date is silently wrong, and the matcher (which only
considers photos from the checklist's own day) skips the photo entirely.

This file's naming convention gives a second source of truth: titles start
with the date ("October 7 2026", "Oct 7-04008", "June 7-26"). When the title
names a day earlier than `date_taken`, that's the real capture day: an
upload-time fallback can only ever be *later* than the real date, never
earlier, so a later title date is more likely a typo and is ignored.

Flickr's `date_taken` is never overwritten. This module derives the
effective day on read, so it can't go stale and every sync re-derives it.

A title date gives a day only, not a time. Callers that do time-of-day
matching (the matcher's tight window) must skip photos where
`day_is_from_title` is True and fall back to same-day matching instead.
"""
import re
from datetime import date, datetime

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

# "<Month> <day>" at the very start of the title, optionally followed by a
# 4-digit year. Whatever follows (" - IH", "-04008", " heron") is ignored.
# The (?!\d) guards stop "May 2026" being read as "May 20".
_TITLE_DATE_RE = re.compile(
    r"^\s*(?P<month>[A-Za-z]{3,9})\.?\s+(?P<day>\d{1,2})(?!\d)(?:[,\s]+(?P<year>\d{4})(?!\d))?"
)


def parse_title_date(title: str | None, taken: datetime) -> date | None:
    """The date a title names, or None. `taken` is Flickr's date_taken,
    used to pick a year when the title doesn't give one."""
    if not title:
        return None
    m = _TITLE_DATE_RE.match(title)
    if not m:
        return None
    month = _MONTHS.get(m.group("month").lower())
    if month is None:
        return None
    day = int(m.group("day"))
    try:
        if m.group("year"):
            return date(int(m.group("year")), month, day)
        candidate = date(taken.year, month, day)
        # No year in the title: the photo can't have been taken after it
        # was "taken", so a candidate in the future means last year's.
        if candidate > taken.date():
            candidate = date(taken.year - 1, month, day)
        return candidate
    except ValueError:  # e.g. "Feb 30"
        return None


def effective_day(photo) -> tuple[date | None, bool]:
    """(day, day_is_from_title) for a photo. day is None when
    `date_taken` is missing or unparseable."""
    try:
        taken = datetime.fromisoformat(photo.date_taken)
    except (TypeError, ValueError):
        return None, False
    title_day = parse_title_date(photo.title, taken)
    if title_day is not None and title_day < taken.date():
        return title_day, True
    return taken.date(), False


def effective_datetime(photo) -> datetime | None:
    """Flickr's timestamp with the title's day swapped in when the title
    corrects it. Time of day is kept only so photos stay in shooting order
    when grouped; it is not a real capture time when the day came from the
    title."""
    try:
        taken = datetime.fromisoformat(photo.date_taken)
    except (TypeError, ValueError):
        return None
    day, from_title = effective_day(photo)
    if from_title:
        return datetime.combine(day, taken.time())
    return taken

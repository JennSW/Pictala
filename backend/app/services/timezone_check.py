"""Timezone-mismatch detection (issue #6).

The matcher's time-window comparison silently assumes every checklist
and every photo's `date_taken` are wall-clock time in the *same* zone.
That's usually true (everything happens near home), but breaks the
moment a camera's clock wasn't updated while traveling -- the photo's
timestamp is still off by whatever the camera *thought* the offset was
minus what it actually should have been at that location.

This module answers one question: for a given checklist (which has real
GPS coordinates) and a photo with a known EXIF `utc_offset` (see
flickr_exif.py), do they disagree about what UTC offset should be in
effect? If so, that's a strong, non-hypothetical signal the photo's
`date_taken` needs a manual correction before it'll ever match correctly
by time.
"""
from datetime import date, datetime, timedelta

from timezonefinder import TimezoneFinder
from zoneinfo import ZoneInfo

from app.models import Checklist, Photo

_tf = TimezoneFinder()


def _parse_offset(offset_str: str) -> timedelta | None:
    """"-08:00" / "+02:00" -> timedelta. None if unparseable."""
    try:
        sign = 1 if offset_str[0] == "+" else -1
        hours, minutes = offset_str[1:].split(":")
        return sign * timedelta(hours=int(hours), minutes=int(minutes))
    except (IndexError, ValueError):
        return None


def _format_offset(td: timedelta) -> str:
    total_minutes = int(td.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    return f"{sign}{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def expected_utc_offset(lat: float, lon: float, on_date: date) -> timedelta | None:
    """The real UTC offset in effect at (lat, lon) on `on_date`, DST
    included -- derived from the coordinates themselves, not hardcoded to
    any one home timezone, so this works the same for a Seattle park
    outing or a trip to a different time zone."""
    tz_name = _tf.timezone_at(lat=lat, lng=lon)
    if tz_name is None:
        return None
    return ZoneInfo(tz_name).utcoffset(datetime.combine(on_date, datetime.min.time()))


def check_mismatch(photo: Photo, checklist: Checklist) -> dict | None:
    """None if there's nothing to flag (missing data on either side, or
    they agree). Otherwise a dict describing the mismatch, including
    `hours_diff` -- the correction a "shift this photo's time" action
    would need to apply."""
    if not photo.utc_offset or not checklist.latitude or not checklist.longitude:
        return None
    try:
        checklist_date = datetime.fromisoformat(checklist.date).date()
    except ValueError:
        return None

    actual = _parse_offset(photo.utc_offset)
    expected = expected_utc_offset(checklist.latitude, checklist.longitude, checklist_date)
    if actual is None or expected is None or actual == expected:
        return None

    diff = expected - actual
    return {
        "photo_utc_offset": photo.utc_offset,
        "expected_utc_offset": _format_offset(expected),
        "hours_diff": diff.total_seconds() / 3600,
    }

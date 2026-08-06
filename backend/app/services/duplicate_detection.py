"""Duplicate photo detection (issue #39, phase 1: detect + flag only,
no auto-action -- a re-upload of the same shot as a separate Flickr
photo, caught after the fact and cleaned up by hand on 2026-08-04 and
again during the July 11 review).

Heuristic, v3 (the one that actually works -- see v1/v2 below for why
they didn't). A photo's title is flagged as a likely duplicate of
another only when ALL of these hold:

  1. Stripping a trailing "copy"/"-N" suffix from it yields a base
     title.
  2. That base title's own trailing digit run is at least 4 digits
     long -- a real camera/Lightroom frame number (e.g. "02239"), not
     a small day-counter or calendar day.
  3. That base title also exists as its own separate real photo, on
     the same calendar day.

Verified against live data on 2026-08-06: finds exactly 4 groups,
including the two known real cases -- "July 11-02239" / "July
11-02239-2" and "July 11-02022" / "July 11-02022 copy" -- with zero
false positives.

Why not simpler (v1/v2, both tried and rejected against real data):

v1 -- strip the suffix, group by what's left. This account's normal
naming convention is itself sequential dash-numbers ("June 7-1"
through "June 7-26" are 26 genuinely different photos, the "-N" *is*
the photo's own number), syntactically identical to the real duplicate
signature. Flagged 499 of 594 real photos -- useless.

v2 -- only flag when the stripped base also exists as its own real
title (drops requirement 2 above). Better, but some days number
sequentially starting unsuffixed ("June 8", "June 8-2", "June
8-3"...), so the bare base legitimately exists as photo #1 of the day
and still false-positived on those.

v3 adds the frame-number-length check: "June 8" ends in "8" (1 digit,
the day of month), while "July 11-02239" ends in "02239" (5 digits, a
real frame number) -- the two patterns are actually distinguishable,
just not by title-matching alone.

Same calendar day, not exact date_taken: a real duplicate pair found
live on 2026-08-06 (photo 348, "July 11-02239-2") had a *different*
exact timestamp than its non-suffixed sibling, because one export had
real EXIF and the other fell back to upload time.
"""
import re

from sqlalchemy.orm import Session

from app.models import Photo

_SUFFIX_RE = re.compile(r"(\s*-\s*\d+|\s+copy\s*\d*)$", re.IGNORECASE)
_TRAILING_DIGITS_RE = re.compile(r"(\d+)$")
MIN_FRAME_NUMBER_DIGITS = 4


def _strip_suffix(title: str) -> str | None:
    """Returns the title with one trailing duplicate-signature suffix
    removed, or None if the title has no such suffix at all."""
    stripped = _SUFFIX_RE.sub("", title.strip()).strip()
    return stripped if stripped and stripped != title.strip() else None


def _looks_like_a_frame_number(base_title: str) -> bool:
    """True if `base_title` ends in a long enough digit run to be a
    real camera/Lightroom frame number rather than a small day-counter
    or calendar day (see module docstring, v3)."""
    m = _TRAILING_DIGITS_RE.search(base_title)
    return bool(m) and len(m.group(1)) >= MIN_FRAME_NUMBER_DIGITS


def find_duplicate_groups(db: Session) -> dict[int, list[int]]:
    """Returns {photo_id: [other photo ids sharing its duplicate
    group]} for every photo with at least one likely duplicate --
    see module docstring for the matching rule."""
    photos = db.query(Photo).filter(Photo.title.isnot(None)).all()

    # (exact title, calendar day) -> photos with that exact title on
    # that day -- the lookup used to check "does the stripped base
    # exist as its own real photo".
    by_exact: dict[tuple[str, str], list[Photo]] = {}
    for p in photos:
        day = (p.date_taken or "")[:10]
        if not day:
            continue
        by_exact.setdefault((p.title.strip().lower(), day), []).append(p)

    result: dict[int, list[int]] = {}
    for p in photos:
        day = (p.date_taken or "")[:10]
        if not day:
            continue
        base = _strip_suffix(p.title)
        if not base or not _looks_like_a_frame_number(base):
            continue
        base_matches = by_exact.get((base.lower(), day), [])
        if not base_matches:
            continue
        group_ids = {p.id} | {m.id for m in base_matches}
        for gid in group_ids:
            existing = result.setdefault(gid, [])
            for other in group_ids:
                if other != gid and other not in existing:
                    existing.append(other)
    return result

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

Scale note: detection itself needs a full-library scan (there's no way
to know a photo is a duplicate without comparing it against the rest of
the library), but that scan only needs to happen once per sync, not
once per page view. `compute_duplicate_group_keys` below is the pure
algorithm (easy to unit test, no DB writes); `recompute_and_store`
runs it once and persists the result onto `Photo.duplicate_group_key`
(see models.py); `get_duplicates_for_photo` is the cheap read path a
request actually takes -- one indexed `WHERE duplicate_group_key = ?`
instead of re-deriving the whole library's groups on every request.
Three call sites (outings.py, unassigned.py x2) all used to pay the
full scan on every single page load; now they don't pay anything extra
at all.
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


def compute_duplicate_group_keys(photos: list[Photo]) -> dict[int, str]:
    """Pure function: given a list of photos, returns {photo_id: group
    key} for every photo that's part of a likely-duplicate group -- see
    module docstring for the matching rule. No DB access here, so this
    is straightforward to unit test against a list of fake Photo rows.

    The group key itself (not an arbitrary id) is what two duplicate
    photos share -- "{base title}|{calendar day}" -- so grouping is just
    "do these rows have the same string", both here and at read time."""
    # (exact title, calendar day) -> photos with that exact title on
    # that day -- the lookup used to check "does the stripped base
    # exist as its own real photo".
    by_exact: dict[tuple[str, str], list[Photo]] = {}
    for p in photos:
        if not p.title:
            continue
        day = (p.date_taken or "")[:10]
        if not day:
            continue
        by_exact.setdefault((p.title.strip().lower(), day), []).append(p)

    result: dict[int, str] = {}
    for p in photos:
        if not p.title:
            continue
        day = (p.date_taken or "")[:10]
        if not day:
            continue
        base = _strip_suffix(p.title)
        if not base or not _looks_like_a_frame_number(base):
            continue
        base_key = (base.lower(), day)
        base_matches = by_exact.get(base_key, [])
        if not base_matches:
            continue
        group_key = f"{base_key[0]}|{base_key[1]}"
        result[p.id] = group_key
        for m in base_matches:
            result[m.id] = group_key
    return result


def recompute_and_store(db: Session) -> int:
    """Run duplicate detection once over the whole library and persist
    the result onto Photo.duplicate_group_key -- call this from the
    sync pipeline (see sync.py), not from a request handler. Clears the
    key on photos no longer in any group (a title edit on Flickr can
    dissolve a group between syncs), so this is safe to call repeatedly.
    Returns the number of photos whose stored key actually changed."""
    photos = db.query(Photo).all()
    new_keys = compute_duplicate_group_keys(photos)
    changed = 0
    for p in photos:
        key = new_keys.get(p.id)
        if p.duplicate_group_key != key:
            p.duplicate_group_key = key
            changed += 1
    db.commit()
    return changed


def get_duplicates_for_photo(db: Session, photo: Photo) -> list[Photo]:
    """Cheap read-time lookup -- an indexed equality query, not a
    library scan. Empty list if `photo` isn't part of any stored group
    (including if a sync hasn't run since duplicate_group_key was
    added -- see recompute_and_store)."""
    if not photo.duplicate_group_key:
        return []
    return (
        db.query(Photo)
        .filter(Photo.duplicate_group_key == photo.duplicate_group_key, Photo.id != photo.id)
        .all()
    )

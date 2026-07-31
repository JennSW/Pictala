"""Strategy A: rule-based matching between checklists and photos.

Deliberately the whole matching story for v1 -- see DESIGN.md section 4 for
why this comes before any model call. Three rules, in order:

1. TIME WINDOW: a photo matches a checklist if its `date_taken` falls within
   [start - PADDING, start + duration + PADDING]. Padding absorbs the fact
   that you don't stop shooting the second the checklist timer ends.
2. SAME-DAY FALLBACK: real eBird exports include a lot of "Casual
   Observation" checklists whose recorded time is when the sighting was
   entered into eBird, not when it actually happened -- sometimes off by
   hours from the real outing. When rule 1 finds nothing for a checklist,
   fall back to matching any photo taken on the same calendar day (and
   within a looser GPS radius, when both sides have coordinates). These
   matches are recorded with a distinct method/lower confidence so the UI
   can show them as looser than a tight time-window match, not hide the
   distinction.
3. SPECIES TEXT MATCH (optional, only if the checklist matched): a photo
   matches a specific observation within that checklist if the species'
   common name (or a simple alias) appears in the photo's title or tags.

Everything here is pure and synchronous on purpose -- no network calls, no
model calls -- so it's trivial to unit test and to point at in a code
review as "this is the deterministic layer."
"""
import math
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Checklist, Photo, Match

WINDOW_PADDING = timedelta(minutes=30)
MAX_MATCH_DISTANCE_KM = 5.0  # tight time-window match: GPS tiebreaker cutoff
SAME_DAY_MAX_DISTANCE_KM = 15.0  # same-day fallback: looser "general area" cutoff


def _parse_checklist_time(time_str: str):
    """eBird exports have used both 24-hour ("18:17") and 12-hour AM/PM
    ("06:17 PM") time formats depending on export version -- try each in
    turn rather than assuming one. Returns a `time` object, or None if the
    string doesn't match any known format (so the checklist still gets a
    window, just anchored at midnight, instead of being dropped entirely)."""
    time_str = time_str.strip()
    for fmt in ("%I:%M %p", "%I:%M:%S %p", "%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(time_str, fmt).time()
        except ValueError:
            continue
    return None


def _checklist_window(checklist: Checklist) -> tuple[datetime, datetime] | None:
    if not checklist.date:
        return None
    try:
        start = datetime.fromisoformat(checklist.date)
    except ValueError:
        return None

    if checklist.start_time:
        parsed_time = _parse_checklist_time(checklist.start_time)
        if parsed_time is not None:
            start = start.replace(hour=parsed_time.hour, minute=parsed_time.minute)

    duration = timedelta(minutes=checklist.duration_minutes or 60)
    return (start - WINDOW_PADDING, start + duration + WINDOW_PADDING)


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _species_text_match(photo: Photo, common_name: str) -> bool:
    """Real Flickr tags are conventionally space-stripped for multi-word
    terms (e.g. "tuftedpuffin", not "tufted puffin") -- a literal
    substring check against the common name alone silently misses every
    multi-word species name (i.e. most of them), even when the tag is
    clearly present. Check the space-stripped form too, not just the
    exact one."""
    haystack = f"{photo.title or ''} {photo.tags or ''}".lower()
    name = common_name.lower()
    return name in haystack or name.replace(" ", "") in haystack


def run_rule_based_matching(db: Session) -> dict:
    """Match every unmatched photo against every checklist. Idempotent-ish:
    clears and rebuilds rule_based matches each run (cheap at this scale)."""
    db.query(Match).filter(Match.method.in_(["rule_based", "rule_based_same_day"])).delete()

    checklists = db.query(Checklist).all()
    photos = db.query(Photo).all()

    # Parse each photo's timestamp once rather than once per checklist.
    parsed_photos = []
    for photo in photos:
        try:
            taken = datetime.fromisoformat(photo.date_taken)
        except ValueError:
            continue
        parsed_photos.append((photo, taken))

    checklist_matches = 0
    species_matches = 0
    same_day_fallback_matches = 0

    for checklist in checklists:
        if not checklist.date:
            continue
        try:
            checklist_date = datetime.fromisoformat(checklist.date).date()
        except ValueError:
            continue

        window = _checklist_window(checklist)

        candidates = []
        method = "rule_based"

        if window:
            start, end = window
            for photo, taken in parsed_photos:
                if not (start <= taken <= end):
                    continue
                if (
                    checklist.latitude
                    and checklist.longitude
                    and photo.latitude
                    and photo.longitude
                ):
                    dist = _haversine_km(
                        checklist.latitude, checklist.longitude, photo.latitude, photo.longitude
                    )
                    if dist > MAX_MATCH_DISTANCE_KM:
                        continue
                candidates.append(photo)

        if not candidates:
            # Nothing in the tight window -- fall back to same-day matching
            # (see module docstring, rule 2) rather than reporting zero.
            method = "rule_based_same_day"
            for photo, taken in parsed_photos:
                if taken.date() != checklist_date:
                    continue
                if (
                    checklist.latitude
                    and checklist.longitude
                    and photo.latitude
                    and photo.longitude
                ):
                    dist = _haversine_km(
                        checklist.latitude, checklist.longitude, photo.latitude, photo.longitude
                    )
                    if dist > SAME_DAY_MAX_DISTANCE_KM:
                        continue
                candidates.append(photo)

        for photo in candidates:
            observation_id = None
            for obs in checklist.observations:
                if _species_text_match(photo, obs.common_name):
                    observation_id = obs.id
                    species_matches += 1
                    break

            db.add(
                Match(
                    checklist_id=checklist.id,
                    photo_id=photo.id,
                    observation_id=observation_id,
                    method=method,
                    confidence=1.0 if method == "rule_based" else 0.5,
                )
            )
            checklist_matches += 1
            if method == "rule_based_same_day":
                same_day_fallback_matches += 1

    db.commit()
    return {
        "checklist_photo_matches": checklist_matches,
        "species_level_matches": species_matches,
        "same_day_fallback_matches": same_day_fallback_matches,
    }


# Strategy B (AI-assisted species suggestion) intentionally does NOT live in
# this file -- see app/services/species_classifier.py and
# app/routers/match.py. This module stays pure/network-free on purpose (see
# the module docstring); the AI-assisted path is a separate module precisely
# so the two are easy to point at separately as "the deterministic layer"
# vs. "the AI layer" in a code review.

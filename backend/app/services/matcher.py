"""Strategy A: rule-based matching between checklists and photos.

Deliberately the whole matching story for v1 -- see DESIGN.md section 4 for
why this comes before any model call. Three rules, in order:

1. TIME WINDOW: a photo matches a checklist if its `date_taken` falls within
   [start - PADDING, start + duration + PADDING]. Padding absorbs the fact
   that you don't stop shooting the second the checklist timer ends.
2. SAME-DAY FALLBACK: real eBird exports include a lot of "Casual
   Observation" checklists whose recorded time is when the sighting was
   entered into eBird, not when it actually happened -- sometimes off by
   hours from the real outing. Also catches the opposite case: a photo
   whose own timestamp is wrong (bad camera clock, wrong recorded
   timezone offset) and so falls outside a checklist's tight window even
   though it's genuinely from that outing. Applied per photo, not
   per checklist -- a checklist with strong tight-window matches from
   rule 1 can still separately pick up same-day photos rule 1 missed
   (issue #59; previously this only ran when rule 1 found *zero* matches
   for the whole checklist, so an outlier photo on an otherwise
   well-matched day silently got no match at all instead of falling back).
   Same-day matches use a looser GPS radius (when both sides have
   coordinates) and are recorded with a distinct method/lower confidence
   so the UI can show them as looser than a tight time-window match, not
   hide the distinction.
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

    # Whatever's left at this point was made by a person (manual, AI-suggested
    # accept, AI fallback) -- a fresh rule-based guess must never duplicate
    # one of those, or _get_or_create_match's .one_or_none() lookup breaks
    # (see issue tracker: this crashed accepting a fallback ID on a photo
    # that had already been fixed once, because a later matcher run added a
    # second row for the same checklist+photo pair).
    already_matched = {
        (m.checklist_id, m.photo_id) for m in db.query(Match).all()
    }

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

        tight_candidates = []
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
                tight_candidates.append(photo)

        # Same-day fallback (issue #59): additive per photo, not
        # conditional on the tight window finding nothing -- a checklist
        # with plenty of tight-window matches can still separately pick
        # up an outlier same-day photo (wrong camera clock/timezone) that
        # rule 1 missed, instead of that photo getting no match at all.
        tight_ids = {p.id for p in tight_candidates}
        same_day_candidates = []
        for photo, taken in parsed_photos:
            if photo.id in tight_ids:
                continue
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
            same_day_candidates.append(photo)

        for photo, method in [(p, "rule_based") for p in tight_candidates] + [
            (p, "rule_based_same_day") for p in same_day_candidates
        ]:
            if (checklist.id, photo.id) in already_matched:
                continue

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

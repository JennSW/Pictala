"""Photo/species grouping for the outing review UI (issue #43).

Deliberately kept as pure computation over already-loaded data (an
outing's deduped matches + its observations), separate from any
particular UI layout -- the explicit ask was to have the underlying
groupings ready before the visual design is settled, so a later UI
change doesn't need this data reshaped differently.

Four buckets, computed unconditionally (cheap at this scale) -- which
ones a given UI shows, and how they're labeled, is a presentation
decision that lives in the frontend, not here:

  ebird_and_flickr   -- photos matched to a real reported observation
  flickr_best_guess  -- photos with a fallback ID, not on this outing's
                         checklist
  needs_claude       -- unmatched photos, nothing identified yet
  ebird_no_photo     -- observation ids with zero matched photo at all

Resolved UI treatment as of the docs/mockups/outing-grouping-mockup.html
iteration (see DESIGN.md §10.3): the mockup merges ebird_and_flickr and
flickr_best_guess into one "To review" / "Confirmed" list (a bird icon
is the only thing distinguishing them, not a separate column or a
relabel of flickr_best_guess itself), and ebird_no_photo is titled
"No photos on Flickr". Both are presentation-only regroupings of the
same four buckets below -- nothing to change here for those.

"Not a bird" (the mockup's fourth post-review bucket, for photos that
genuinely aren't birds and can never resolve to a species) has **no
backend representation yet**. There's currently no way to distinguish
"still needs Claude" from "Claude looked and it's not a bird" in this
data -- a fallback identification only ever records a species guess,
never an explicit not-a-bird flag. Whoever builds the real grouping UI
will need to add that (e.g. a boolean on Match, or accept-fallback
recording is_bird) before "Not a bird" can be a real bucket here rather
than a mockup placeholder.

Whether an outing counts as "reviewed" is a stored flag
(Checklist.outing_reviewed_at on the group's primary checklist), not
computed from these buckets -- see models.py and app/routers/outings.py.
"""
from app.models import Match, Observation


def compute_photo_groups(matches: list[Match], observations: list[Observation]) -> dict:
    """`matches` should already be deduped to one Match per photo (see
    outings.py's matches_by_photo) -- this doesn't do that itself."""
    ebird_and_flickr: list[int] = []
    flickr_best_guess: list[int] = []
    needs_claude: list[int] = []
    matched_observation_ids: set[int] = set()

    for m in matches:
        if m.observation_id is not None:
            ebird_and_flickr.append(m.photo_id)
            matched_observation_ids.add(m.observation_id)
        elif m.fallback_common_name is not None:
            flickr_best_guess.append(m.photo_id)
        else:
            needs_claude.append(m.photo_id)

    ebird_no_photo = [o.id for o in observations if o.id not in matched_observation_ids]

    return {
        "ebird_and_flickr": ebird_and_flickr,
        "flickr_best_guess": flickr_best_guess,
        "needs_claude": needs_claude,
        "ebird_no_photo": ebird_no_photo,
    }

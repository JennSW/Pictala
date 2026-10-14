# BirdTrip — User Stories

> Where this document cites an issue by number, it refers to the project's [issues board](https://github.com/JennSW/Pictala/issues).

Backlog of user-facing stories, grouped by feature area. Each story follows:
**As a / I want / so that** → Description → Acceptance Criteria → Priority → Notes.

Shared behavioral rules that would otherwise bloat every story that touches
them live in a "Functional Spec" block above the relevant story group, and
individual stories reference it rather than repeating it.

**Diagrams:** the matching logic below is also drawn out in
[`docs/diagrams/`](diagrams/) — [outing grouping](diagrams/outing-grouping-flow.svg),
[species-level matching](diagrams/species-matching-flow.svg), and
[fallback identification](diagrams/fallback-identification-flow.svg).

---

## Feature: Outing grouping

### Story: Group checklists by date + Location ID

**As a** birder, **I want** checklists from the same trip grouped into one
outing, **so that** a single trip that produced multiple eBird checklists
(e.g. 4 separate submissions at Smith Island on the same day) shows up as
one outing instead of several, and a photo doesn't appear as an unresolved
candidate across checklists it doesn't belong to.

**Description:** Discovered via a real case: 4 separate `7/12` Smith
Island checklists all surfaced the same Tufted Puffin photo as a "matched
photo" candidate, since checklist-to-photo matching runs independently
per checklist. The fix is grouping checklists themselves before matching,
not just handling it in review.

**Resolved: grouping key is date + eBird Location ID** (e.g. `L73431432`
for Smith Island), not location *name* and not a GPS radius. A fixed
radius doesn't generalize — Lake Merritt outings are walkable within half
a mile, while Smith Island is spread over several miles of open water.
eBird's own Location ID already encodes "this is one place" at whatever
scale that place actually is, so using it sidesteps per-location radius
tuning entirely.

**Acceptance Criteria:**
- Given multiple checklists share the same date and eBird Location ID,
  when outings are listed, then they appear as a single combined outing,
  not one entry per checklist.
- Given a combined outing, then its species list is the union of
  observations across all grouped checklists.
- Given a photo matches the combined outing's time/place window, when
  its species is checked, then it's checked against the union of species
  across the group — matched if any grouped checklist reported it,
  unmatched otherwise.
- Given the CSV importer currently discards eBird's "Location ID" column
  (only location *name* is stored today), then this requires capturing it
  on `Checklist` as a prerequisite.

**Priority:** High — directly fixes a confirmed real bug (the duplicate
Tufted Puffin candidate across 4 checklists).

**Notes:**
- Resolves the open question previously tracked in the *Species ID
  fallback for eBird gaps* story about same-day multi-checklist ambiguity.
- Side benefit: Strategy B's candidate list also becomes the group's
  union of species, so an uncaptioned photo gets checked against all of a
  trip's reported species at once, not just whichever single checklist it
  happened to land under.
- **Open issue, not solved here:** photo-to-checklist distance matching
  (`matcher.py`'s 5km tight-match / 15km same-day-fallback cutoffs) is a
  separate mechanism from this grouping key, and may independently need
  revisiting for a large-area case like Smith Island, where photos taken
  from a boat could fall outside a fixed cutoff even when they're clearly
  part of the same trip. Explicitly parked, not resolved.
- **Deeper finding (2026-07-31), also parked, not investigated further:**
  checked the real data — 95/95 checklists have coordinates, but 0/500
  photos do. The GPS-distance tiebreaker only runs `if checklist.latitude
  and checklist.longitude and photo.latitude and photo.longitude` (all
  four), so with photo coordinates always empty, that tiebreaker has
  never actually executed against any real data — it's been silently
  inert this whole time, not just imperfectly tuned. Whether that's
  Flickr stripping geotags on upload, photos never being geotagged, or a
  sync gap wasn't investigated — explicitly on hold per the user's call.
- Future consideration, not decided: should the automatic grouping be
  manually overridable (split/merge) in the review UI for cases the rule
  gets wrong? Raised in discussion, not yet turned into a story.

### Problem: Time zone handling in time-window matching (not yet decided)

`matcher.py` compares `checklist.date`/`start_time` against
`photo.date_taken` as naive datetimes — no time zone attached on either
side, compared directly. This works only if both sides happen to be in
the same local time. Not hypothetical: the real synced data already
includes a trip to a different time zone.
If a checklist was logged in local time at the destination but a camera's clock was
never updated for the time change (common when traveling), the tight
time-window match goes silently off by the offset — and if the offset
pushes a photo's date across midnight, even the same-day fallback fails,
since that's still keyed on calendar date. No solution proposed yet.

---

## Feature: Sync (eBird + Flickr)

### Functional Spec: Sync behavior

- Two trigger types: **automatic** (fires on outings-page load) and
  **manual** (a "Sync now" button).
- Independent daily budgets: automatic = 1x/day, manual = 4x/day. Budgets do
  not share a pool.
- "Day" means a **calendar day in the user's own time zone** (resets at
  midnight local time, not UTC or the server's time zone) — not a rolling
  24-hour window.
- Every attempt counts toward its budget regardless of success or failure.
- A sync (of either type) covers today plus any unsynced, *unsaved* days
  since the last successful sync.
- Any day whose results have already been saved/locked (see *Save results*
  story) is always skipped by sync, regardless of trigger type — this is
  how saved results are protected from being overwritten.
- eBird retrieval: the regional checklist-feed endpoint
  (`/product/lists/{regionCode}/{y}/{m}/{d}`), filtered to a configured
  eBird display name (no direct "my checklists" API exists). Flickr
  retrieval: existing date-range sync, unchanged.
- Requires one-time setup: eBird display name, region code(s), and the
  user's time zone (for calendar-day resets), following the same pattern
  as the existing `.env`-based API keys.
- Rate-limit and last-synced state must persist across app restarts (not
  in-memory only).
- Original bulk-history CSV import is unaffected — this spec only covers
  ongoing, day-to-day updates.

### Story: Manual sync

**As a** birder, **I want** a manual "Sync now" button I can use up to 4
times a day, **so that** I can pull in fresh results right after I finish
uploading photos to Flickr, without waiting for the next automatic sync.

**Acceptance Criteria:**
- Given fewer than 4 manual syncs have occurred today, when I click "Sync
  now," then a sync runs immediately per the Sync behavior spec.
- Given 4 manual syncs have already occurred today, then the button is
  disabled and shows when it becomes available again.

**Priority:** High

---

### Story: Automatic sync on page load

**As a** birder, **I want** the app to automatically check for new eBird
and Flickr data once a day when I open it, **so that** I don't have to
remember to sync manually just to see current results.

**Acceptance Criteria:**
- Given the automatic sync hasn't run yet today, when the outings page
  loads, then a sync runs automatically per the Sync behavior spec.
- Given the automatic sync has already run today, when the page loads
  again, then no sync runs, and the page shows the last-synced time.

**Priority:** High

---

### Story: Sync never overwrites saved days

**As a** birder, **I want** a day's results to stay exactly as I saved
them, **so that** a later sync can never quietly change or overwrite my
finalized review.

**Acceptance Criteria:**
- Given a day's results have been saved/locked, when any sync runs (auto
  or manual), then that day is excluded entirely — no checklist or photo
  data is re-pulled for it.

**Priority:** High

**Notes:**
- Depends on the *Save results* story (not yet drafted) for what "saved"
  means.
- Open question, not yet resolved: if new photos surface for an
  already-saved day, there's currently no way to reopen/unlock it. Revisit
  when drafting *Save results*.

---

## Feature: Species identification

### Already built (context, not a new story)

Per `DESIGN.md` and prior sessions: Strategy A does deterministic
species-level matching (a photo matches a specific observation if the
species name appears in its title/tags). Strategy B adds an opt-in
"Suggest species" action for *uncaptioned* photos that already matched a
checklist — Claude picks from that checklist's own ~5–15 reported species
only. Backend + frontend for this are complete; only blocked on the
Anthropic API key. Nothing here changes that path.

### Story: Manual species assignment

**As a** birder, **I want** to manually pick a species when Strategy B
reports no confident match, **so that** I can correct a false negative
instead of being stuck with no way to record the right answer.

**Description:** Built 2026-07-31, discovered live: testing Marymoor
Park's single-candidate European Starling checklist, Strategy B got 4 of
5 photos right and incorrectly reported "no match" on the 5th, which was
also a Starling. Even in the easiest possible case (one candidate
species), the AI isn't perfectly accurate — the UI needs a way to correct
it, not just accept/dismiss what the AI proposes.

**Acceptance Criteria:**
- Given a "no confident match" result, when I pick one of the outing's
  own reported species from a list and confirm, then the photo is matched
  to that species — no AI suggestion required first.
- Given a manually-assigned match, then it's recorded distinctly (method
  `manual`) from an AI-confirmed one (`ai_suggested`), so provenance stays
  honest.

**Priority:** High — small, contained, fixes a real accuracy gap found in
testing.

**Notes:**
- Backend reuses the existing accept endpoint's pattern
  (`POST /match/{checklist_id}/assign/{photo_id}`); no new matching logic.
- Built alongside the fallback story below, since both are ways of
  handling a "no confident match" result and share the same UI location.
- **Extended 2026-07-31:** rejecting a *positive* suggestion (the AI
  named a specific candidate species, but it's wrong) used to just clear
  the guess with no follow-up at all. Now it shares this exact same
  panel — manual dropdown, "Try broader ID," a plain note field — plus a
  "Try Again" button that re-runs the constrained guess, since a wrong
  suggestion and no suggestion both mean "this proposed answer isn't
  right." The plain note field reuses the fallback accept endpoint with
  no AI guess behind it at all (an arbitrary label with no species
  metadata is exactly what an "Other" entry already is).

### Story: Species ID fallback for eBird gaps

**As a** birder, **I want** BirdTrip to attempt species identification on
photos that don't have a confirmed species match, **so that** I still get
a species suggestion whether that's because the outing wasn't logged in
eBird at all, or because I photographed something I didn't get around to
reporting.

**Description:** Extends "Suggest species" to two related cases, per the
hybrid matching decision (see `PRD.md` Section 4). (1) A photo doesn't
fall into any checklist's time/GPS window at all (no logged outing). (2) A
photo matches a checklist, but the checklist-constrained guess comes back
"none" — e.g. a real, discovered case: a Wood Duck photo matched to the
Lake Merritt outing by time/place, but Wood Duck wasn't one of the species
actually reported that day. Both cases fall back to a broader,
less-constrained species guess from Claude, using the photo's title/tags
as hints if present. eBird's taxonomy is then queried to resolve standard
metadata (`speciesCode`, `comName`, `sciName`) for whatever Claude
proposes.

**Resolved: this never writes back to eBird, automatically or otherwise.**
eBird's public API doesn't support writing to a checklist anyway. Approving
a fallback suggestion labels the photo with the species (photo-level only
— it does not alter the checklist's own "Species seen" list or count
toward it) and surfaces a link to the real checklist on eBird.org so I can
add it there myself, manually, if I want it reflected in my actual eBird
record.

**Acceptance Criteria:**
- Given a photo has no matching checklist, when I trigger species
  suggestion on it, then Claude is asked to identify the bird species,
  using the photo's title/tags as hints if available.
- Given a photo matched a checklist but the checklist-constrained guess
  returned no match, when I trigger species suggestion again, then the
  same broader, less-constrained guess runs.
- Given Claude proposes a species, when the suggestion is returned, then
  eBird's taxonomy is queried to resolve `speciesCode`, `comName`, and
  `sciName` for that species.
- Given Claude can't identify a bird with reasonable confidence, or
  determines the photo isn't a bird at all, then the photo is flagged
  accordingly (non-bird / unidentifiable) rather than forced into a guess.
- Given any suggestion (bird or flagged), then it's shown with a
  confidence indicator and requires explicit approval before being saved —
  nothing is written automatically, same suggest-then-accept discipline as
  the existing checklist-constrained flow.
- Given I approve a fallback suggestion, then the photo is labeled with
  the species, and a link to the relevant checklist on eBird.org is shown
  so I can manually add it there — BirdTrip never writes to eBird itself.
- Given this calls a paid API, then it's triggered manually per photo (a
  "Suggest species" action), not run automatically — same cost discipline
  as the existing flow.

**Priority:** Medium — depends on the Anthropic API key (now working) and
is secondary to the already-built checklist-constrained path.

**Built 2026-07-31**, covering trigger case (2) — checklist matched,
constrained guess returned none — verified live with a real Heron photo
on a Starling-only Marymoor checklist. Trigger case (1), no matching
checklist at all, is still unbuilt: there's nowhere in the UI for an
orphaned photo to appear yet (see *Feature: Outing grouping*'s
checklist-less photo clusters, also still unbuilt).

**Notes:**
- Additive to, not a replacement for, the existing checklist-constrained
  flow.
- Suggestions here feed into the same review UI as everything else
  (approve/remove/park, edit) — see *Results review* (not yet drafted),
  not a separate screen.
- ~~Open: how far should "less-constrained" reach?~~ Resolved by
  implementation: fully open-vocabulary (no region/season narrowing),
  with the guess resolved against eBird's real taxonomy afterward
  (`app/services/ebird_taxonomy.py`).
- Found live: the model's `is_bird` flag is sometimes inconsistent with
  its own successful identification (reported `is_bird: false` while
  correctly naming Great Blue Heron with 85% confidence). Frontend only
  trusts `is_bird` when no species name came back at all; a resolved
  identification is treated as a bird regardless of that flag.
- **"Other" category, added 2026-07-31** — found live testing a photo of
  a dragonfly: the original design treated a name that doesn't resolve
  against eBird's bird taxonomy as unidentified and discarded it. Changed
  that: the model now always gives its best guess at what's shown, bird
  or not (e.g. "Eight-spotted Skimmer" for a dragonfly), and a
  non-bird guess is offered as a legitimate "Other" category rather than
  an error — same `fallback_common_name` field, just with
  `fallback_species_code` staying null, so no schema change was needed to
  distinguish the two. The guess is shown in an editable text field
  (pre-filled, not just a fixed Accept button), so the user can save it
  as-is or overwrite it with their own note before saving.
- ~~Open: same-day-multiple-checklists ambiguity~~ — resolved by the
  *Group checklists by date + Location ID* story above (Feature: Outing
  grouping), not by review-workflow or matcher tie-breaking.

### Problem: Batches of same-species photos (not yet decided)

Real example: a Smith Island trip with many Tufted Puffin photos, only
some of which are captioned. Two related issues, not yet resolved:

- **Efficiency** — "Suggest species" is a manual, per-photo, paid action.
  A batch of many uncaptioned photos of the same bird means many
  individual clicks/calls for what is, in practice, one identification.
- **Accuracy/consistency** — each photo is judged by Claude in isolation
  today. A clear, close-up shot and a blurry/distant shot of the same bird
  moment could get different answers, since nothing lets the confident
  results inform the ambiguous ones.

**Suggested solution (not locked in):** send a *burst* of related photos
to Claude in a single call instead of one photo at a time, so ambiguous
shots get the benefit of context from clearer ones in the same batch.
Requirements this raises, unresolved:
- A "burst" grouping key tighter than the outing grouping (which spans a
  whole day) — likely a short time window at the same spot. The threshold
  itself isn't decided.
- Claude must return a result *per photo*, not one verdict for the whole
  burst, since a burst could still mix species.
- Pairs naturally with the original bulk-approve idea from the brainstorm
  notes (multi-select → Approve/Remove/Park) — a burst suggestion
  producing many results is exactly what that UI was for.
- Reduces clicks and improves consistency, but does **not** reduce cost —
  sending N images in one call still costs roughly what N individual
  calls would.

**Concrete UI mechanism decided (2026-07-31), implementation still
deferred:** a checkbox on each unmatched photo, plus a "Match All" button
that sends every checked photo to Claude in one call. This is the
mechanism for the bulk-approve pairing above, not just a burst-grouping
detail — tracked as issue #5 (issue #22, a near-duplicate filed the same
day, was merged into this one).

Applies to both the constrained flow (Strategy B) and the eBird-gap
fallback above — same mechanism, different candidate list. Left open for
further exploration before turning into a formal story.

### Problem: Caption-based matches are trusted blindly (not yet decided)

Strategy A's species text/tag match (`_species_text_match` in
`matcher.py`) confirms a match purely because a species name appears in
the photo's caption/tags — with no visual check at all. If a photo is
mis-tagged on Flickr (wrong species typed into the caption), it's
recorded as a confident, confirmed match and no AI safety net ever fires,
since that only runs for *uncaptioned* photos today. This is a gap in the
"never silently trust it" principle the rest of the design otherwise
follows — a wrong caption is currently indistinguishable from a right one.
No solution proposed yet.

## Feature: Results review (edit, approve, flag, save)

### Conceptual structure (confirmed; UX not yet designed)

For a single trip that has at least one checklist (e.g. Smith Island),
results break into three buckets:

1. **Photos with a match** — confirmed species match (text/tag match, or
   an approved Strategy B suggestion).
2. **Photos without a match** — taken during the trip but not tied to any
   of its reported species (includes both the checklist-constrained "none"
   case, like the Wood Duck, and anything not yet run through the
   fallback flow).
3. **Birds without a photo** — species the checklist(s) reported that have
   no matching photo at all. New bucket, not previously captured —
   completes the picture in both directions (photos missing a species,
   and species missing a photo).

This is distinct from checklist-less photo clusters (*Feature: Outing
grouping*) — those have no checklist/trip to belong to at all, whereas
these three buckets exist *within* a real trip.

Interaction design for each bucket (what actions are available, layout,
etc.) is intentionally not decided yet — captured here as structure only,
per the brainstorm notes' review-workflow ideas (edit, approve/remove/park,
save) still needing to be mapped onto this.

**UI requirements to design against (see `PRD.md` Section 4):**
- Accessibility compliant, usable by screen readers. How links and alt
  text on photos should be handled is still to be worked out.
- A webpage for now — usable on desktop, with a mobile layout.

## Feature: Search & browse

Motivating use case (see `PRD.md` Section 5): sharing a specific photo
with birding friends in the field by looking it up by species, not by
browsing outings one at a time.

### Story: Search by species

**As a** birder, **I want** to search my photos by species name, **so
that** I can quickly pull up and share a specific photo without browsing
outings one at a time.

**Description:** Reuses existing data — no new matching logic or external
calls. Covers every confirmed match: caption/tag text matches, approved
Strategy B suggestions, and approved eBird-gap fallback labels (per the
earlier decision that a photo-only label is still fully searchable, not
just a name shown on the photo).

**Acceptance Criteria:**
- Given I enter a species name (or partial name) in search, when results
  return, then I see every photo confirmed matched to that species,
  regardless of which matching path confirmed it, each showing its date
  and outing.
- Given no photos match the searched species, then I see a clear "no
  matches" state, not an error.
- Given multiple photos match across different outings, then results are
  sorted most-recent-first, consistent with the outings list.
- Given a search result, when I select it, then I can view the full photo
  (with its Flickr page link, per the PRD's in-scope photo-linking
  requirement) directly, without navigating through the outing list.
- Given search input, then matching is case-insensitive and works on
  partial common names — scientific name matching is not required for v1.

**Priority:** Medium — short and well-scoped, but a UX nicety rather than
core matching functionality.

**Notes:**
- Out of scope for v1: full-text search over captions/notes, typo-tolerant
  fuzzy matching, search by location.
- Only searches confirmed matches (Bucket 1) — unmatched/pending photos
  aren't surfaced here, consistent with never treating an unverified
  suggestion as fact.

### Story: Date selection

**As a** birder, **I want** to jump straight to a specific date, **so
that** I can find a known outing without scrolling the full chronological
list.

**Description:** v1 scope is a single-date picker, not a date range —
keeps this short. Complements *Search by species* as the other way to
narrow results outside of browsing outings chronologically.

**Acceptance Criteria:**
- Given the date picker, then only dates with at least one outing are
  selectable — dates with no outings are greyed out and disabled
  (`aria-disabled`, not just visually distinct), not merely styled
  differently while still clickable.
- Given the set of dates with outings, then it's derived client-side from
  the outings list already loaded on the page — no new backend endpoint
  needed.
- Given a disabled date, then clicking/tapping it does nothing.
- Given I pick an enabled date, when results update, then I see only the
  outing(s) that occurred on that date.
- Given I clear the date selection, then the view returns to the full
  chronological outings list, unchanged from today's default behavior.
- Given the page loads with no date selected, then all outings show as
  they do today — date filtering is opt-in, not required, and the list
  itself stays unfiltered.
- Given the page loads with no date selected, then the detail panel
  defaults to the most recent outing instead of sitting empty — the list
  being unfiltered and the detail panel defaulting to the latest outing
  are independent behaviors, not in conflict.
- Given the date picker is opened, then it defaults to showing the
  current real-world month, not the month of the most recent outing or
  any other outing-derived default.

**Priority:** Medium — same reasoning as *Search by species*.

**Notes:**
- Greyed-out + disabled was chosen over a bold/not-bold distinction
  specifically for the accessibility requirement (`PRD.md` Section 4) —
  font weight alone doesn't communicate anything to a screen reader,
  disabled state does.
- The original "empty state for a selected date with no outings" scenario
  becomes a defensive fallback rather than the primary path, since a
  disabled date can't be selected in the first place.
- A date-*range* filter is a natural future enhancement, not required now.

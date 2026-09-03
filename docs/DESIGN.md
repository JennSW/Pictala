# BirdTrip — Design Doc

A portfolio project that pairs your eBird checklists with your Flickr photos so
each outing shows what you saw and what you shot, side by side. Built to be a
talking piece in interviews: it has a real (small) data problem, a real
architectural choice about where "AI" belongs, and real tradeoffs to defend.

## 1. What it does

1. Pulls your eBird checklists (species, date, time, location, count) for a
   date range.
2. Pulls your Flickr photos for the same date range (title, date taken, GPS
   if present, tags).
3. Matches each checklist to the photos most likely taken on that outing, and
   within a checklist, tries to match individual photos to individual species.
4. Renders a per-outing page: map pin, species list, matched photos.

## 2. Why this is a good interview artifact

It's small enough to build in a weekend but touches things that come up in
real system design conversations:

- Two third-party APIs with *different* auth models (API key vs OAuth 1.0a) —
  forces you to explain both, not just one.
- A genuinely fuzzy matching problem (photos and checklists don't share a
  foreign key) — you get to show reasoning about heuristics vs ML, not just
  "I called an endpoint."
- A believable spot for AI to add value *or* to be overkill — which is the
  most interview-relevant tradeoff of all: knowing when not to reach for a
  model.

## 3. The data problem, precisely

Neither API gives you a clean join key.

- eBird checklists have: date, start time, duration, location (lat/lon +
  named hotspot or personal location), species + counts.
- Flickr photos have: date taken (from EXIF, can be wrong if the camera clock
  was never set), optional GPS (only if the camera/phone had GPS and the user
  didn't strip it), title/description/tags (user-written, inconsistent).

So "match a photo to a checklist" is really "match a photo to a time+place
window," and "match a photo to a species" is really "match a photo to
whatever the user happened to type in the title/tags" — unless you add
vision.

## 4. Two matching strategies (the tradeoff to present)

### Strategy A — Rule-based (build this first)

For each checklist, define a window: `[start_time - 30min, start_time +
duration + 30min]`. Assign a photo to a checklist if its `date_taken` falls in
that window, breaking ties by GPS distance to the checklist location when
both have coordinates. Within a checklist, match a photo to a species only if
the species name (or a common alias) appears in the photo's title/tags.

Pros: no ML infra, fully deterministic, explainable in one sentence, zero
marginal cost per photo, works offline. Cons: fails silently when EXIF time
is wrong (very common — cameras drift), and species-level matching only
works for photos the user bothered to caption, which in practice is a small
minority.

### Strategy B — AI-assisted species matching (the stretch goal)

For photos in a matched checklist window that have *no* usable caption, run
an image classifier (a bird-species vision model, or a general vision-language
model like CLIP / a hosted multimodal API) against the checklist's species
list only — i.e., constrain the classifier to the ~5-15 species actually
reported on that outing rather than open-vocabulary "what bird is this,"
which is a much easier and cheaper problem than general species ID.

Pros: recovers matches for the (common) uncaptioned photos, and the
constrained-classification framing is itself worth explaining in an
interview — "I didn't do open-set bird ID, I used the checklist as a strong
prior to turn it into a 5-way classification problem." Cons: adds a model
dependency, a cost per photo, and a confidence threshold you have to tune and
expose in the UI (show the guess, let the user confirm/reject) rather than
silently trusting it.

**Recommendation:** ship Strategy A completely first — it's the whole app
and it works. Add Strategy B as an opt-in "AI suggest" button on unmatched
photos. This ordering is itself a good interview answer: rules first,
ML for the residual, never the reverse.

## 5. Architecture

```
                    ┌─────────────────────────┐
                    │        Frontend         │
                    │   React + TypeScript    │
                    │  (Vite, runs locally)   │
                    └────────────┬────────────┘
                                 │ REST (JSON)
                    ┌────────────▼────────────┐
                    │      FastAPI backend     │
                    │  - /outings              │
                    │  - /outings/{id}/photos  │
                    │  - /sync/ebird           │
                    │  - /sync/flickr          │
                    │  - /match/{id}/suggest   │  (Strategy B, optional)
                    └───┬───────────────┬──────┘
                        │               │
              ┌─────────▼───┐   ┌───────▼──────┐
              │ eBird client │   │ Flickr client │
              │ (API key)    │   │ (OAuth 1.0a)  │
              └─────────┬────┘   └───────┬───────┘
                        │                │
              ┌─────────▼────────────────▼───────┐
              │   SQLite (local file, checked in  │
              │   schema, gitignored data)         │
              │  checklists, observations, photos,  │
              │  matches, sync_log, ai_suggestion_log│
              └───────────────────────────────────┘
```

### 5a. Data model

Full entity-relationship diagram: [`diagrams/data-model.svg`](diagrams/data-model.svg).

Six tables. `Checklist` and `Observation` come from eBird; `Photo` comes
from Flickr. `Match` is the central join table — one row per photo,
linking it to a `Checklist` and optionally an `Observation`, with
`method`/`confidence` recording how the link was made (rule-based,
AI-suggested, manual, or AI-fallback) and a `fallback_*` label for
species identified off the outing's own checklist. It only ever holds
the *current* state of that link.

`AiSuggestionLog` (added 2026-09-03, for AI accuracy tracking — see
`GET /stats/ai-accuracy`) is deliberately **not** a foreign key off
`Match` — it logs every AI suggestion and its outcome
(accepted/corrected/rejected) independently, so a rejected or
overwritten suggestion isn't lost the way it would be if `Match` were
the only record. `SyncLog` is unrelated to the rest — just a row per
manual sync, enforcing the daily limit.

Everything runs locally (`uvicorn` + `vite dev`) — no deployment needed for a
screen-share demo, which keeps auth simple: store your own API keys and
Flickr OAuth token in a local `.env`, never multi-tenant, never touching
other people's credentials.

## 6. Tech stack and why

| Layer | Choice | Why |
|---|---|---|
| Backend | Python + FastAPI | Typed, async, auto-generates OpenAPI docs (nice for a demo — show `/docs` live), and Python is the natural home if Strategy B (vision model) gets added later. |
| DB | SQLite via SQLAlchemy | Zero setup, single file, fine for one user's data. Explicitly call out in the demo that this wouldn't scale past one user — Postgres would be the production answer. |
| Frontend | React + TypeScript + Vite | Fast dev loop, typed contracts with the backend via a shared OpenAPI-generated client, standard enough that any interviewer recognizes it instantly. |
| Matching | Plain Python (Strategy A) + optional model call (Strategy B) | Keeps the "AI" part isolated behind one function (`suggest_species(photo, candidate_species)`) so it's easy to point at in a code review. |

## 7. Data acquisition specifics

**eBird**: Get a personal API key at the eBird API key page (tied to your
eBird account, instant approval). The live API (base
`https://api.ebird.org/v2/`, key sent as header `x-ebirdapitoken`) is built
around *regional* queries (recent observations in a region, checklist feeds
for a region/date) rather than "give me all of my own checklists" — there is
no simple "my history" endpoint. The practical route for a personal history
is eBird's own **Download My Data** export (My eBird → Download My Data),
which gives you a CSV of every checklist and observation you've ever
submitted (date, time, location, species, counts). Use the CSV as the
primary ingestion path and treat the live API as an enhancement (e.g.,
looking up hotspot names or recent regional activity), not the source of
your own history. This split — export for bulk personal history, live API
for point lookups — is a good tradeoff to narrate.

**Flickr**: Create an app at Flickr's app-creation page to get an API
key/secret, then do a one-time 3-legged OAuth 1.0a flow (since you're only
ever accessing your own account, you do this once locally and store the
resulting token — no need to build a full login system). Once authorized,
`flickr.people.getPhotos` / `flickr.photos.search` with your own `user_id`
and `min_taken_date`/`max_taken_date` gets you photos in a date range;
request `extras=date_taken,geo,tags,url_m` to get what you need in one call
instead of one call per photo.

## 8. Roadmap

1. **Foundation** — FastAPI skeleton, SQLite schema, `.env` config, health
   check endpoint.
2. **eBird ingestion** — CSV importer for the Download-My-Data export;
   populate `checklists` + `observations` tables.
3. **Flickr ingestion** — OAuth flow (one-time script), photo fetch by date
   range, populate `photos` table.
4. **Strategy A matching** — time-window + GPS-distance matcher, persisted
   into a `matches` table.
5. **Frontend** — outing list, outing detail page (map + species + photos).
6. **Strategy B (stretch)** — "AI suggest" button using a constrained vision
   classifier for uncaptioned photos, with a confidence badge and
   accept/reject UI.
7. **Polish for the demo** — seed script with a few real outings, README with
   architecture diagram and the tradeoff writeup above (interviewers read
   READMEs).

## 9. What to say if asked "where's the AI"

The honest answer is the strongest one: most of the app is deterministic
because deterministic is the right tool for a well-defined join problem.
The AI is scoped to exactly the sub-problem that's genuinely open-ended
(identifying a bird in a photo with no caption) and even there it's
constrained by the checklist to a small candidate set rather than solving
open-vocabulary species ID from scratch. That scoping — and the decision to
surface it as a suggestion with a confidence score rather than an automatic
overwrite — is the actual engineering judgment on display.

## 10. Visual & UX design decisions

The app is moving from function-first to a refined, shareable UI (tracked in
#4, brand direction in #48). Decisions below are the confirmed starting
point; open items are called out explicitly rather than left implicit.

### 10.1 Scope: entry screen first

Of the four candidate screens (entry/home, outing detail's #43 grouping, the
checklist-less cluster view, search results), the **entry screen ships
first** — everything else depends on how a user lands in the app.

Confirmed entry-screen flow:
1. Greeting + new-activity prompt: "Hello Jen! You have X new trips in eBird
   and X new trips in Flickr. Do you want to review them now?" — lists just
   names/dates, not full checklists/photos yet.
   - Yes → loads the matching UI.
   - No → the new-trip names/dates persist with a "needs review" reminder
     until acted on.
2. **Last 3 trips**, promoted to the hero section — larger cards, real
   photo thumbnail where available (thumbnail-left/text-right per §10.3).
   Revised from the first wireframe pass: a full-size calendar there was
   visually dominant and worked against the app's actual point (what you
   saw + what you shot on a trip), so the trip cards now lead.
3. **Calendar**, demoted to a compact secondary widget below the trips —
   smaller cells, muted heading, no card border/shadow — still answers "is
   there something new" without competing for attention. Three visual
   states (bold font doubles as the "today" indicator, so this isn't a
   color-only accessibility issue — see 10.5):
   - **Today**: bold font, distinct background, linked if it has a trip.
   - **Day with a trip**: bold font, different background than today,
     linked.
   - **Day with no trip**: default background, regular weight, not linked.

### 10.2 Mobile: layout in scope for this pass

Mobile **responsive layout** is in scope now, not deferred — the entry
screen in particular (prompt + calendar + trip list stacked) risks getting
visually busy, so the layout needs to be designed mobile-first rather than
retrofitted after a desktop-only pass. This is still the webpage described
in section 1 (usable on desktop with a mobile layout); it is not a native
mobile app build.

### 10.3 Outing-review grouping (#43) — UX resolved

Worked out live against real Marymoor Park data in
[docs/mockups/outing-grouping-mockup.html](mockups/outing-grouping-mockup.html)
(day-toggle between the real data and a hypothetical stress-test day
included in the mockup — see its own in-file notes for the full back-and-
forth). Supersedes the original 3-groupings sketch from #4 (the "Flickr,
not on eBird, hidden behind a See other photos button" idea) — the more
precise split below came out of actually building it.

**Before review** — still an active work queue, so nothing here is
collapsed or hidden:
- **To review**: eBird-matched and Flickr-best-guess photos merged into
  one list — a small bird icon marks the eBird-matched ones (on eBird =
  icon, guess-only = no icon), same convention as "Confirmed" below.
  eBird-matched entries sort first.
- **Needs Claude**: no guess yet.

**After review**:
- **Confirmed**: eBird-matched and guess-confirmed birds merged into one
  list, same bird-icon convention, eBird-linked entries first. Replaces
  "Flickr + best guess" — once approved, the user only cares that a
  species was identified and signed off on, not whether it came from an
  eBird match or an AI guess.
- **No photos on Flickr**: eBird species with no matching photo, in its
  own list under its own heading — not mixed into the photo grid, since
  it's a species entry, not a photo card.
- **Not a bird**: **reopens** the earlier "Needs Claude disappears
  entirely after review" answer (confirmed on #4). That assumed every
  unresolved photo eventually resolves to a species ID; it doesn't --
  some photos genuinely aren't birds (people, gear, landscape shots mixed
  into a Flickr upload) and can never become a species match, so they
  need a permanent post-review list rather than vanishing.

**Layout**: one wide primary column plus a narrow sidebar, not
equal-width columns side by side (three or more read as cluttered).
Positions are **fixed, not sorted by list length**: "To review" (before)
and "Confirmed" (after) are always the wide primary column; "Needs
Claude" (before) and "No photos on Flickr" + "Not a bird" (after) always
stay in the sidebar, regardless of which list is actually longer on a
given day. Sorting the primary column by count was tried and reverted —
it made "Needs Claude" jump from the wide column to the sidebar depending
on the day's data, which read as the page rearranging itself under the
user rather than just showing different numbers. Fixed position, even
when it means a long sidebar next to a short primary column, was judged
less confusing than layout that moves.

The after-review sidebar's two sections are **collapsed by default**
(native `<details>`, accessible without extra work) — both "No photos on
Flickr" and "Not a bird" can get very long on some days, and neither
should dominate the sidebar by default. The before-review sidebar stays
**uncollapsed** — it's still open work, not a settled edge case, so
hiding it risks it being ignored.

Selection state (multi-select on photo grids): a circle containing a
checkmark, restyled from the current bright-blue default — not a bare
circle with no checkmark.

Thumbnail-left/text-right (the Audubon "Filter ID" reference, see 10.4)
is the **app-wide card layout**, replacing the old top/bottom stack
(photo on top, label below) everywhere — not limited to the
unidentified/best-guess list it was originally referenced for.

### 10.4 Brand direction (#48)

Reprioritizing the Brand Book's palette for this app rather than applying
its primary/secondary/tertiary hierarchy as-is:

| Role | Color | Note |
|---|---|---|
| Dominant | `#3C689A` (navy) | Book's tertiary, promoted to lead |
| Secondary accents | `#AB7F99` (mauve), `#A3B899` (sage), `#728CFF` (periwinkle), `#E38A99` (rose) | |
| Reserved, narrow use | `#8BE9FF` (cyan) | Flagged as possibly too bright; candidate for the multi-select checkmark specifically |
| Dropped | `#FFC7A7` (peach), `#D19FFF` (light purple) | Not carried forward |

Background: **white**, for this first design session — the cream canvas was
a placeholder, not a decision. Revisit once more of the UI (navy-dominant)
is actually built out.

Typography: Brand Book specifies SF Compact Text (Regular/Bold/Heavy), but
it's an Apple system font not generally cleared for embedding on a public
website. **Aptos was checked and ruled out**: it's a Microsoft-proprietary
font tied to Office/365's license, not sold or offered as a standalone
webfont license, and Microsoft's own font-embedding terms prohibit
exporting/redistributing the font file outside a Microsoft product — so it
can't be legally self-hosted or served as a webfont on an independent site.
**Decided: Public Sans** — SIL Open Font License (free to self-host, no
royalties, no attribution required), multiple weights and italics, built by
the US government's 18F for federal websites, which fits the "clean,
accessible, institutional" register this app's accessibility requirement
(10.5) already leans toward.

Logo: the Brand Book's **simplified/secondary logo** (single mauve circle,
peach outline ring, white checkmark) is the primary logo for BirdTrip, not
the full three-overlapping-circle version.

Reference screenshots (attached to #48) and what they anchor:
- Wellness app home screen — rounded cards, background/card contrast, small
  icon badge lower-left on thumbnails.
- Bird-photo grid select behavior — plain round circle preferred over a bare
  checkmark for the selected state (superseded by 10.3's resolved
  circle-containing-checkmark), plus a slight lightness shift on selected
  cards.
- Audubon "My Life List" — cream background, serif heading, alphabetical
  section chips, common name regular / scientific name italic — direct match
  for the eBird-no-photo list (10.3).
- Audubon "Filter ID" — thumbnail left, common+scientific name stacked
  right — now the app-wide card layout (10.3), originally referenced for
  the unidentified/best-guess list specifically.

### 10.5 Standing accessibility rule

Never use color as the sole indicator of status or differentiator (already
required by #4's PRD-linked accessibility requirement) — every colored state
above pairs with a shape, icon, label, or weight change, not color alone.

### 10.6 Open items

- [ ] Calendar widget (10.1) — demoted and shrunk per the trip-promotion
      revision, but still not right. Not yet specified what's wrong
      (size, position, the trip-day styling, or something else) —
      revisit once it's clearer what to fix.

### 10.7 Link to eBird's species page (#48)

**Question:** once there's a confirmed match, or on the eBird-no-photo
list, can the species name link out to eBird's own page for that species
so the user can read more?

**Answer: yes — technically straightforward, not yet built.**

eBird hosts a public species page at `https://ebird.org/species/{speciesCode}`
(e.g. `https://ebird.org/species/comrav` for Common Raven) — verified live:
loads with no sign-in required (identification info, range map, photos,
"Learn more from Birds of the World" all visible anonymously; it only gates
personal stats/badges behind login). The species code is eBird's own stable
taxonomy ID, not something BirdTrip would need to guess at or maintain.

The catch is where that code comes from. It's already on `Match.fallback_species_code`
for fallback-identified photos (manual/AI/note guesses resolved against
eBird's taxonomy in `unassigned.py`/`match.py`), but **not** on `Observation`
(the real eBird checklist entries — i.e. every confirmed match and every
entry on the eBird-no-photo list) — the CSV import path
(eBird's Download My Data export) simply doesn't include a species-code
column, only common/scientific name (verified against
`backend/seed_data/sample_ebird_export.csv`'s header row).

That's a smaller gap than it sounds: `app/services/ebird_taxonomy.py`
already fetches and in-process-caches eBird's full ~18k-species taxonomy
(comName → speciesCode) for exactly this kind of resolution — it's just
only ever called for fallback guesses today. The same `find_species()`
lookup works for `Observation.common_name` too, since eBird checklist
exports use eBird's own canonical common names. Two implementation options,
either viable:
- Resolve on the fly at read time (call `find_species()` when serializing
  an outing/observation) — no schema change, small per-request cost.
- Store `species_code` on `Observation` at CSV-import time (mirroring how
  `Match.fallback_species_code` already works) — one-time cost per import,
  nothing to resolve later.

Not yet implemented — this documents feasibility for whenever the
confirmed-match / eBird-no-photo UI actually gets built.

### 10.8 eBird-match icon (#48) — resolved

**Problem:** the "on eBird" indicator (10.3's bird icon, marking eBird-matched
entries in "To review"/"Confirmed") can't actually use eBird's own logo —
it's a recognizable trademark BirdTrip has no license to use if this ever
became public. Needed a replacement that doesn't need eBird's mark to make
the same "matched" claim.

**Decided:** a licensed list/notebook stock icon (reads as "logged on a
checklist," which is conceptually honest to what eBird actually is) —
icon present = eBird-matched, absent = guess-only. Same on/off meaning
the old bird-icon emoji carried, new (licensed, trademark-free) icon.

**Placement, revised after being built into the real app:** originally a
corner badge on the photo thumbnail (tested and initially chosen over an
inline-before-the-label placement — see the mockup history below). Once
actually built into the live outing page against real bird photos rather
than mockup placeholders, the same badge that read fine in isolation
interfered with the photo itself — Jen's call. **Moved inline**: the icon
now sits below the common name, next to the scientific name when one
exists, not overlapping the thumbnail at all. Also fixed in the same
pass: the icon's visibility was originally conditioned on a scientific
name being present, which would silently hide it whenever that field's
missing — and it turns out eBird's single-checklist CSV export (as
opposed to the full history export) has no scientific-name column at
all, so that gap wasn't hypothetical. The icon now shows unconditionally
whenever a photo is eBird-matched, scientific name present or not.

A second licensed icon (camera) was tested alongside it as the answer to "how
do we also show a photo exists," but it's **not used** on the "To
review"/"Confirmed" screen specifically — every card there is already a
Flickr photo by definition, so a "has a photo" badge would be on 100% of
cards and distinguish nothing. Reserved for a future view where photo
presence isn't already implied by the card itself (e.g. a per-species summary
row that may or may not have a photo attached) — that's also where the
original "how do we show a species is on both eBird and Flickr" question
actually gets answered: two independent badges that can co-occur, rather
than one icon trying to carry both meanings.

Mockup history (superseded by the real-app revision above, kept for
context): the corner-badge version was worked out live against real
thumbnails in
[docs/mockups/outing-grouping-icons-mockup.html](mockups/outing-grouping-icons-mockup.html)
(a variant of 10.3's grouping mockup with only the icon swapped,
everything else unchanged) — thumbnail 60×60px (up from 10.3's original
44px), badge 24px circle, white background, thin border, `object-fit:
contain`. Earlier passes at a smaller badge (18px, then down to 11px)
looked identically oversized regardless of the container size — turned
out to be a CSS specificity bug (an unscoped `.thumb img` rule was also
matching the badge's inner `<img>`, forcing it to the full 44px thumbnail
size with `object-fit: cover`), not an actual sizing question. The exact
same class of bug recurred once ported into the real app's `theme.css`
(same unscoped-selector mistake, independently made and independently
fixed) before the placement itself changed.

Current (real app): 60×60px thumbnail unchanged; the icon itself is a
small 13px inline image next to the scientific name, no badge/circle/
border — see `frontend/src/theme.css`'s `.ebird-match-icon` and
`App.tsx`'s `renderMatchCard()`.

Icon colors (lavender camera, peach list) are provisional — both are close to
colors 10.4's brand-direction table explicitly dropped
(`#D19FFF`, `#FFC7A7`). Jen's call: icon badges need to contrast against
whatever's in the photo itself, which is a different goal than the rest of
the UI chrome's palette, so this may intentionally diverge from 10.4's
dropped-colors list rather than being an oversight. Not yet reconciled;
revisit once final icon colors are picked from the Brand Book.

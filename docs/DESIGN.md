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
              │  matches                             │
              └───────────────────────────────────┘
```

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

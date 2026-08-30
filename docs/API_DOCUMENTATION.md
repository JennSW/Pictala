# BirdTrip API Reference

Curated reference for the BirdTrip backend (FastAPI, `backend/app/main.py`).
Written for a mixed audience — engineers integrating against it, and
non-engineering stakeholders (Product, Legal, Trust & Safety) who need to
understand what data moves where without reading source. Auto-generated
interactive docs are also available at `/docs` (Swagger UI) when the
server is running; this document adds the "why," not just the "what."

**Base URL (local dev):** `http://localhost:8000`
**Auth:** none today — see [MULTI_USER_AUTH_SCOPING.md](MULTI_USER_AUTH_SCOPING.md)
for the plan to change that.

---

## Resource map

| Router | Prefix | Purpose |
|---|---|---|
| `outings` | `/outings` | Read/review grouped eBird checklists ("outings") |
| `match` | `/match` | AI-assisted + manual photo↔species matching, checklist-scoped |
| `unassigned` | `/unassigned` | Same matching workflow for photos with no eBird checklist |
| `search` | `/search` | Search confirmed matches by species |
| `sync` | `/sync` | Data ingestion: eBird CSV upload, Flickr pull, re-matching |
| — | `/health` | Liveness check |

---

## `outings` — grouped checklists

An "outing" is one or more eBird checklists sharing a date + location,
grouped automatically (`app/services/outing_grouping.py`).

| Method | Path | Description |
|---|---|---|
| GET | `/outings` | List all outings, newest first — location, date, species count, photo count, review status |
| GET | `/outings/{outing_id}` | Full detail: all observations, all photo↔species matches, per-photo timezone-mismatch and duplicate flags |
| POST | `/outings/{outing_id}/mark-reviewed` | Mark an outing as fully reviewed (explicit, stored state — not computed from "any photos left to match") |
| POST | `/outings/{outing_id}/unmark-reviewed` | Clear reviewed status |

`{outing_id}` accepts any checklist id belonging to the group — the group's
lowest checklist id is the canonical id returned by the list endpoint.

---

## `match` — checklist-scoped photo matching

Two-step by design: a `suggest*` endpoint proposes and persists nothing; an
`accept*`/`assign` endpoint is the only thing that writes a match. There is
deliberately no `/reject` — declining a suggestion just means never
calling accept.

| Method | Path | Description |
|---|---|---|
| POST | `/match/{checklist_id}/suggest/{photo_id}` | AI guess constrained to this outing's own reported species. Nothing persisted. |
| POST | `/match/{checklist_id}/accept/{photo_id}` | Persist an AI suggestion as a confirmed match |
| POST | `/match/{checklist_id}/assign/{photo_id}` | Manually assign one of the outing's reported species, no AI involved |
| POST | `/match/{checklist_id}/suggest-fallback/{photo_id}` | Broader, unconstrained AI guess for a photo matching nothing on the checklist. Nothing persisted. |
| POST | `/match/{checklist_id}/suggest-fallback-batch` | Same, batched — one AI call for a set of photos instead of one round-trip each |
| POST | `/match/{checklist_id}/accept-fallback/{photo_id}` | Persist a fallback identification (typed or AI-suggested); resolves to on-checklist / off-checklist-but-real-species / plain-text note |
| POST | `/match/{checklist_id}/adjust-timezone/{photo_id}` | Apply a camera-clock correction and re-run matching — can move a photo to a different checklist entirely |

---

## `unassigned` — checklist-less photos

Photos with no eBird checklist at all (a captive-bird photo, or a real
outing whose checklist hasn't been uploaded yet), grouped into date-based
clusters (`app/services/photo_clusters.py`). Same identify/confirm pattern
as `match`, minus the "matches this checklist's species" tier, since
there's no checklist to constrain against.

| Method | Path | Description |
|---|---|---|
| GET | `/unassigned` | List clusters — date, photo count |
| GET | `/unassigned/{cluster_id}` | Cluster detail with per-photo match status |
| POST | `/unassigned/{cluster_id}/suggest/{photo_id}` | Unconstrained AI guess. Nothing persisted. |
| POST | `/unassigned/{cluster_id}/suggest-batch` | Batched version |
| POST | `/unassigned/{cluster_id}/identify/{photo_id}` | Persist an identification (typed or accepted AI guess) |
| POST | `/unassigned/{cluster_id}/move/{photo_id}` | Move a photo into a different cluster by correcting its capture date |

---

## `search`

| Method | Path | Description |
|---|---|---|
| GET | `/search?species=<name>` | Case-insensitive partial match on common name, **confirmed matches only** — an inner join through `Observation` naturally excludes unmatched/pending photos |

---

## `sync` — data ingestion

Manual, button-triggered — not scheduled, since the app is currently
single-user/local rather than a running service.

| Method | Path | Description |
|---|---|---|
| POST | `/sync/ebird` | Upload an eBird "Download My Data" CSV export (multipart file) |
| POST | `/sync/flickr?min_taken_date=&max_taken_date=` | Pull + upsert Flickr photos in a date range; refreshes title/tags/coordinates on existing photos too, so edits made on Flickr after the fact still land |
| POST | `/sync/match` | Re-run rule-based matching over everything currently in the DB |
| GET | `/sync/status` | Remaining syncs today, last-synced-at timestamp |
| POST | `/sync/run?min_taken_date=&max_taken_date=` | The "Sync now" button: Flickr pull + re-match in one call, capped at 4/day (calendar day, user's local time zone). Defaults to a 30-day lookback if no range given. |

**Rate limit:** `/sync/run` returns `429` once the daily cap is reached.
Every attempt counts toward the cap regardless of success/failure.

---

## `/health`

`GET /health` → `{"status": "ok"}`. No auth, no DB access — pure liveness
check.

---

## Data-handling notes (for Legal / Trust & Safety review)

- **External data sources:** eBird (user-uploaded CSV, no live API call
  today) and Flickr (OAuth1, pulled via `/sync/flickr`). Both are the
  user's own accounts/data — no third-party personal data ingestion.
- **No auth today:** every endpoint above is currently unauthenticated —
  see [MULTI_USER_AUTH_SCOPING.md](MULTI_USER_AUTH_SCOPING.md) before this
  API is exposed beyond localhost.
- **AI calls:** `suggest*`/`identify` endpoints send a photo URL (+
  species candidate list) to the Anthropic API for a species guess
  (`app/services/species_classifier.py`). No user PII is included in
  those calls beyond what's already in the photo/checklist data itself.

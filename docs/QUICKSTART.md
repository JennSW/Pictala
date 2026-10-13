# Pictala — Quickstart

Matches your eBird checklists to your Flickr photos, outing by outing. (Formerly
BirdTrip; older documents still use that name.) Built as a portfolio project: see
[`DESIGN.md`](DESIGN.md) for the architecture, the eBird/Flickr matching problem, and
the rules-versus-AI tradeoff the project is meant to show.

It runs locally, for one user, by design. There is no hosted version.

## Fastest way: `./start.sh`

From the repository root:

```bash
./start.sh
```

It checks for Python 3.10+ and Node, sets up a private Python environment, installs the
front end, loads the **synthetic sample data** (14 invented outings, no real person's data),
starts both servers, and opens your browser.

With only the sample data you will see outings and species but **no photos**. Photos arrive
only through a Flickr sync, which needs your own credentials (see below).

## Platform notes

This project was designed and built on a MacBook, and a MacBook is the only machine it has
been tested on. It should also run on a Windows or Linux PC, since the app itself contains no
OS-specific code, but **no testing has been done on any platform other than a MacBook**, so
expect to do some troubleshooting elsewhere.

- `start.sh` is written for macOS: it suggests Homebrew installs and uses the macOS `open`
  command to launch the browser. It is a bash script, so on Windows it would at least need
  WSL or Git Bash, and its browser-opening step would not work. On a PC, use the manual
  setup below instead.
- On Windows, activate the Python environment with `.venv\Scripts\activate` rather than
  `source .venv/bin/activate`.

## Manual setup

### 1. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your keys, see below
uvicorn app.main:app --reload
```

Auto-generated API docs are at http://localhost:8000/docs, which is worth pulling up
live in a demo.

### 2. Get your credentials

| What | Needed for | Required? |
|---|---|---|
| **eBird data export** | Your checklists. Download them from https://ebird.org/downloadMyData ("Download My Data"). eBird has no personal-data API, which is why the app imports this CSV (see [`DESIGN.md`](DESIGN.md) section 7). | Yes, for real data |
| **eBird API key** (https://ebird.org/api/keygen, instant) | Species-name lookups only (resolving a typed or suggested name against eBird's species list) | Yes, for those lookups |
| **Flickr app key + secret** (https://www.flickr.com/services/apps/create/) | Fetching your photos | Yes, for photos |
| **Flickr authorization** | A one-time terminal step (below) that gives the app read access to your photos | Yes, for photos |
| **Anthropic API key** (https://console.anthropic.com) | AI species suggestions. The app works without it; AI suggestions are simply unavailable | Optional |

Put the keys in `backend/.env` (see `.env.example`). Never commit `.env`; it is gitignored.

For Flickr, after adding the app key and secret to `.env`, run once from `backend/`:

```bash
python -m app.services.flickr_oauth_setup
```

It prints a Flickr URL to open. Click Authorize, paste the code Flickr shows back into the
terminal, then copy the resulting token, token secret, and user id into `.env`.

**No credentials yet?** `backend/seed_data/sample_ebird_export.csv` has 14 invented outings
(no real person's data; regenerate with `python seed_data/generate_sample_data.py`) so you
can try the CSV import straight away.

### 3. Load data and run matching

In the app, the sync panel has two buttons:

- **Upload eBird CSV** imports checklists and then runs the matcher. Re-uploading is safe:
  your confirmed matches are kept. (If you removed a species from a checklist on eBird, its
  confirmed matches cannot be kept; the app tells you how many.)
- **Sync now** pulls your recent Flickr photos and re-runs matching. It is capped at 4 a day.

The same actions are available from the API page (`/docs`): `POST /sync/ebird`,
`POST /sync/flickr`, and `POST /sync/match`. To run just the matcher:

```bash
curl -X POST http://localhost:8000/sync/match
```

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

## Tests

```bash
cd backend
pytest
```

46 tests across five files:

| File | Covers |
|---|---|
| `test_matcher.py` | The rule-based matcher: the deterministic core, and the part worth being able to defend line by line |
| `test_ebird_import.py` | Re-importing a CSV keeps confirmed species matches (#95), and a first import keeps every species |
| `test_photo_dates.py` | Using the date in a photo's title when Flickr's date is an upload fallback (#34) |
| `test_duplicate_detection.py` | The duplicate-photo heuristic |
| `test_ebird_taxonomy.py` | Species-name resolution |

There are no front-end tests; `npm run build` type-checks the front end. Known coverage
gaps are listed on issue #74.

## Project layout

```
backend/
  app/
    main.py, config.py, db.py   FastAPI app and CORS; settings from .env; database setup
    models.py                   Checklist, Observation, Photo, Match, SyncLog, AiSuggestionLog
    schemas.py                  Pydantic response models
    routers/
      outings.py                list outings, outing detail, mark / unmark reviewed
      match.py                  per-photo actions: suggest, accept, reject, assign, unconfirm, timezone adjust
      unassigned.py             photos with no eBird checklist: clusters, identify, move
      search.py                 search by species
      stats.py                  AI suggestion accuracy
      sync.py                   eBird import, Flickr sync, matching, the "Sync now" button
    services/
      ebird_import.py           eBird CSV importer (DESIGN.md section 7)
      flickr_client.py          OAuth 1.0a Flickr REST calls
      flickr_oauth_setup.py     one-time CLI authorization
      flickr_exif.py            per-photo EXIF lookup
      matcher.py                Strategy A: rule-based matching
      species_classifier.py     Strategy B: AI-assisted species suggestions (optional)
      photo_dates.py            real capture day, with a title-date fallback
      outing_grouping.py        groups checklists into outings
      outing_review.py          groups an outing's photos and species for the review screen
      photo_clusters.py         groups photos that have no checklist
      duplicate_detection.py    flags likely duplicate photos
      timezone_check.py         flags camera-clock timezone mismatches
      ebird_taxonomy.py         common-name to species resolution
  tests/                        see Tests above
  seed_data/                    synthetic sample CSVs and the script that generates them
frontend/
  src/App.tsx                   main UI: outing list, outing review
  src/SyncPanel.tsx             upload and sync controls
  src/DatePicker.tsx, PhotoLightbox.tsx, api.ts, theme.css
docs/                           PRD, design doc, user stories, diagrams, wireframes
start.sh                        one-command local setup (macOS)
```

## Status

Both matching strategies are built. Strategy A (rules, `matcher.py`) matches photos to
outings and, when a photo's title or tags name a species on the checklist, to the species.
Strategy B (`species_classifier.py`) asks a vision model to suggest a species for photos the
rules cannot identify; it is optional and nothing it suggests is accepted without review.
Open work and known limits are tracked in the repository's issues.

# Pictala — Quickstart

> Where this document cites an issue by number, it refers to the project's [issues board](https://github.com/JennSW/Pictala/issues).

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
starts both servers, and opens your browser. The sample data is loaded only when the database
is empty; it is never added to a database that already has outings.

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

## Troubleshooting

Errors appear in a red banner at the top of the page: what went wrong, then a **What to try**
line. The table below covers the common ones. If you started the app with `./start.sh`, the
backend's log is `backend.log` in the project folder; otherwise it is the terminal running
`uvicorn`.

| You see | Why | What to do |
|---|---|---|
| **Can't reach the Pictala backend** | The page can't talk to the backend: it isn't running, or it stopped. | Start it with `./start.sh` (or `uvicorn app.main:app` from `backend/`), then reload. |
| **Flickr isn't connected yet** | One or more Flickr values are missing from `backend/.env`. The message lists which. | Add them, run `python -m app.services.flickr_oauth_setup` once, restart the backend. Without Flickr you can still upload an eBird CSV and browse outings and species. This failure is not counted against your daily syncs. |
| **Flickr rejected your API key** | The key or secret in `.env` is wrong or was revoked. | Re-copy both from https://www.flickr.com/services/apps/ . |
| **Flickr didn't accept your authorization** | The token is missing, expired, or was revoked. | Run `python -m app.services.flickr_oauth_setup` again and paste the new token and secret into `.env`. |
| **Flickr couldn't find that user** | `FLICKR_USER_ID` is wrong. | Use the user id printed by the setup step (it looks like `12345678@N00`). |
| **Flickr is temporarily unavailable** | A problem on Flickr's side. | Wait a few minutes and try again. |
| **Too many photos in that date range** | A sync fetches at most 10,000 photos at once, and refuses to return a partial list. | Sync a narrower range, for example one year at a time. |
| **You've used all 4 syncs for today** | The daily Flickr sync limit. | It resets at midnight. Photos from earlier syncs are still there. Uploading an eBird CSV is not limited. |
| **That doesn't look like an eBird export** | The uploaded file has no species column. | Upload the CSV from eBird's **Download My Data** (https://ebird.org/downloadMyData), or the .zip it emails you; the app unzips it. |
| **That zip file doesn't contain a CSV**, or **couldn't be opened** | The zip is the wrong one or was cut short. | Download it again, or unzip it yourself and upload the CSV inside. |
| **That file is empty**, or **larger than 50 MB**, or **couldn't be read as a text CSV** | Wrong or damaged file. | Check you picked the right file. A real eBird export is far below 50 MB. |
| **Looking up bird names needs an eBird API key** | Species-name lookups need a free key. | Get one at https://ebird.org/api/keygen , set `EBIRD_API_KEY` in `.env`, restart the backend. |
| **eBird didn't accept your API key** | The key is wrong. | Re-copy it from https://ebird.org/api/keygen . |
| **AI suggestions need an Anthropic API key, and none is set** | Suggestions are optional and off until you add one. | Set `ANTHROPIC_API_KEY` in `.env` and restart, or just pick species by hand. |
| **Anthropic didn't accept your API key**, or **is limiting how fast** | A wrong key, a key without access, or too many requests. | Check the key at https://console.anthropic.com . If you keep a workspace, the key must belong to it. For rate limits, wait a minute. |
| **Something went wrong on the server**, with a reference | A bug. The message is generic on purpose; the detail is in the log. | Try again. If it keeps happening, find the reference in the log and include it when you report the problem. |
| **The database is busy or unavailable** | The SQLite file is locked, read-only, or damaged. | Make sure only one copy of the backend is running and that the folder is writable. If the database is damaged, move `backend/birdtrip.db` aside; it is recreated on the next start. (That file holds your imported data, so keep the copy until you've checked.) |

## Tests

```bash
cd backend
pytest
```

114 tests across eleven files:

| File | Covers |
|---|---|
| `test_matcher.py` | The rule-based matcher: the deterministic core, and the part worth being able to defend line by line |
| `test_ebird_import.py` | Re-importing a CSV keeps confirmed species matches (#95), and a first import keeps every species |
| `test_ebird_upload.py` | Uploading eBird files: zip, byte-order mark, wrong files, size limit, no temp copies left behind |
| `test_photo_dates.py` | Using the date in a photo's title when Flickr's date is an upload fallback (#34) |
| `test_duplicate_detection.py` | The duplicate-photo heuristic |
| `test_ebird_taxonomy.py` | Species-name resolution |
| `test_flickr_sync.py` | Fetching every page of Flickr results, and what each Flickr error says to do |
| `test_api_photo_validation.py` | Unknown photo ids are rejected and the database enforces foreign keys |
| `test_error_handling.py` | Every failure comes back readable, with a hint, and with CORS headers |
| `test_service_errors.py` | Anthropic and eBird key and rate-limit failures |
| `test_start_sh.py` | `start.sh` only loads sample data into an empty database |

There are no front-end tests; `npm run build` type-checks the front end. Known coverage
gaps are listed on issue #74.

## Project layout

```
backend/
  app/
    main.py, config.py, db.py   FastAPI app, CORS and error handling; settings from .env; database setup
    errors.py                   one error format for every failure: {detail, hint, error_id}
    models.py                   Checklist, Observation, Photo, Match, SyncLog, AiSuggestionLog
    schemas.py                  Pydantic response models
    routers/
      outings.py                list outings, outing detail, mark / unmark reviewed
      match.py                  per-photo actions: suggest, accept, reject, assign, unconfirm, adjust time zone,
                                broader AI guess (single and batch) and accepting it
      unassigned.py             photos with no eBird checklist: clusters, suggest (single and batch), identify, move
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
  requirements.txt              Python dependencies
  run_dev.sh                    runs the backend with auto-reload on port 8000
  .env.example                  example settings (copy to .env)
frontend/
  src/App.tsx                   main UI: outing list, outing review
  src/SyncPanel.tsx             upload and sync controls
  src/DatePicker.tsx, PhotoLightbox.tsx, api.ts, theme.css, main.tsx
docs/                           PRD, design doc, architecture decisions, user stories, API reference,
                                diagrams, wireframes, screenshots, reviews and session recaps
start.sh                        one-command local setup (macOS)
README.md, LICENSE              overview; PolyForm Noncommercial license
```

## Status

Both matching strategies are built. Strategy A (rules, `matcher.py`) matches photos to
outings and, when a photo's title or tags name a species on the checklist, to the species.
Strategy B (`species_classifier.py`) asks a vision model to suggest a species for photos the
rules cannot identify; it is optional and nothing it suggests is accepted without review.
Open work and known limits are tracked in the repository's issues.

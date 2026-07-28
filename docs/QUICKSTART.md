# BirdTrip

Matches your eBird checklists to your Flickr photos, per outing. Built as a
portfolio project — see `DESIGN.md` for the architecture, the eBird/Flickr
matching problem, and the rule-based-vs-AI tradeoff this project is meant to
showcase.

## Quickstart (local demo, no deployment needed)

### 1. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your keys, see below
uvicorn app.main:app --reload
```

API docs (auto-generated) will be at http://localhost:8000/docs — worth
pulling up live in a demo.

### 2. Get your credentials

- **eBird**: get a key at https://ebird.org/api/keygen (instant). Then export
  your full history from https://ebird.org/downloadMyData ("Download My
  Data") — this CSV is what you'll upload via `/sync/ebird`, not the live
  API (see `DESIGN.md` section 7 for why).
- **Flickr**: create an app at https://www.flickr.com/services/apps/create/
  to get an API key + secret, put them in `.env`, then run:
  ```bash
  python -m app.services.flickr_oauth_setup
  ```
  and paste the resulting token/secret/user id into `.env`.

No real credentials yet? `backend/seed_data/sample_ebird_export.csv` has a
few fake outings so you can try the CSV import and matcher immediately —
upload it via the `/docs` page's `/sync/ebird` endpoint.

### 3. Run the matcher

Once you've synced eBird + Flickr data (via `/sync/ebird` and
`/sync/flickr`, both usable straight from `/docs`), trigger matching:

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

### Tests

```bash
cd backend
pytest
```

Covers the rule-based matcher (`tests/test_matcher.py`) — the deterministic
core of the app, and the part worth being able to defend line-by-line in an
interview.

## Project layout

```
backend/
  app/
    main.py             FastAPI app, CORS, router registration
    models.py           SQLAlchemy models (checklists, observations, photos, matches)
    schemas.py          Pydantic response models
    services/
      ebird_import.py   CSV importer (see DESIGN.md sec. 7)
      flickr_client.py  OAuth1-authenticated Flickr REST calls
      flickr_oauth_setup.py  one-time CLI OAuth handshake
      matcher.py        Strategy A (rule-based) + Strategy B hook
    routers/
      outings.py        GET /outings, GET /outings/{id}
      sync.py           POST /sync/ebird, /sync/flickr, /sync/match
  tests/test_matcher.py
  seed_data/sample_ebird_export.csv
frontend/
  src/App.tsx           outing list + detail view
  src/api.ts            typed fetch wrapper
DESIGN.md               architecture + tradeoffs writeup
```

## Status

This is a scaffold: the backend runs end-to-end (import → sync → match →
serve), the frontend renders real data from it, and the matcher has tests.
Not yet built: the Strategy B ("AI suggest") vision-model hook in
`matcher.py` is stubbed with a clear `NotImplementedError` and a comment on
what to build there — intentionally left as the next milestone (see
`DESIGN.md` section 8).

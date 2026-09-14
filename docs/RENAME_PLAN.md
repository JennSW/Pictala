# BirdTrip Rename — Project Plan

Tracks execution of the rename triggered by the naming conflict discovered
2026-09-01 (see `NAMING_REVIEW.md` and issue #61, "Rename of app"). This
plan covers *what has to change, what can stay the same, and what's still
open* — it does not itself pick the final name. Front-runner as of
2026-09-02 is **Perchoto** (not yet final).

## Status key

- **Blocked on name decision** — can't execute until a final name is chosen.
- **Independent** — should happen on its own timeline, regardless of when
  the name is finalized.
- **Deferred** — no action needed until a name is chosen; safe to ignore
  until then.
- **Open investigation** — unresolved question, needs an answer before
  the task under it can be scoped or executed.

---

## 1. Must change now, independent of the app rename

The app itself isn't deployed anywhere public, but one surface already
is: the public job-search portfolio site. This carries real exposure
today and shouldn't wait on a final app name.

| Item | What needs to happen | Status |
|---|---|---|
| theswiftbrain.com pages (`/birdtrip`, `/birdtrip-kickoff`, `/program-toolkit`) | Swap "BirdTrip" references to a neutral placeholder term, or pause linking new outreach to these slugs, until a final name lands | Independent |
| Published Claude Artifacts ("BirdTrip Program Toolkit," "BirdTrip Kickoff") | Same as above — retitle or hold off sharing until renamed | Independent |
| LinkedIn / outreach content referencing BirdTrip by name | Audit and update wording if/when found | Independent |

**Why this is separate:** this is live, public, and tied to active job
outreach — the only genuine trademark-adjacent exposure that exists
right now, versus the app itself which is still private/local-only.

---

## 2. Must change before any public app launch (not urgent while local-only)

These are the user-visible strings inside the app. None of them need to
move until a name is final and a public deploy is imminent — they're a
contained find-and-replace, not a structural change.

| Location | What it is | Change needed |
|---|---|---|
| `frontend/index.html:6` | `<title>BirdTrip</title>` | Browser tab title |
| `frontend/src/App.tsx:1163` | `<span className="wordmark">BirdTrip</span>` | In-app logo/wordmark |
| `frontend/src/SyncPanel.tsx:147` | "BirdTrip works best with your eBird data…" | User-facing help copy |
| `backend/app/main.py:11` | `title="BirdTrip API"` | Title shown on the auto-generated `/docs` Swagger page once the API is deployed/reachable |

Status: **Blocked on name decision** (or at minimum, safe to batch into
one PR once a name is chosen — small, mechanical, low risk).

---

## 3. Can stay as an internal code name indefinitely

No public or trademark exposure — GitHub repo (`JennSW/BirdTrip`) is
confirmed **private**, so none of this is visible outside the local dev
environment.

| Location | What it is |
|---|---|
| `frontend/package.json:2` | npm package name `birdtrip-frontend` — build metadata only |
| `backend/app/config.py:27` | SQLite filename `birdtrip.db` — local file, never shown to users |
| `frontend/src/App.tsx:120-121` | `localStorage` key `birdtrip_last_load` — invisible outside devtools |
| `frontend/src/App.tsx:740`, `frontend/src/theme.css:1`, `backend/app/schemas.py:93` | Code comments/docstrings — not a FastAPI route docstring, so none surface in API docs |
| `start.sh` | Local dev-run script echo text — seen only by whoever runs it locally |
| `docs/` (PRD, design docs, backlog, README history, etc.) | Private-repo planning docs |

Status: **Deferred**. Rename opportunistically during unrelated edits if
convenient, but nothing here requires a dedicated pass.

---

## 4. External registrations — open investigation

Three things outside the codebase are also named BirdTrip. None of
these block feature work; they're tracked here so they don't get
forgotten when the rename actually happens.

| Item | Open question | Status |
|---|---|---|
| GitHub repo `JennSW/BirdTrip` (private) | None — renaming is a simple settings change; GitHub auto-redirects the old clone URL, so the local `git remote` won't break | **Done 2026-09-14**: renamed to `JennSW/Pictala`. Confirmed the old URL redirects (`git ls-remote`, `gh api` both resolved), then pointed the local `origin` remote at the new canonical URL. The GitHub Project board was also renamed, "Jen Swift BirdTrip" → "Jen Swift Pictala" (same project ID, no items affected). |
| eBird API key | None — tied to the account rather than a public "app name" | Low risk, no action needed |
| Flickr API app (registered in Flickr's App Garden) | ~~Unconfirmed: is renaming a simple dashboard edit, or does it require re-registering with new keys/secrets?~~ **Resolved 2026-09-14**: Jen renamed the app to "Pictala" in the App Garden dashboard; confirmed via a live `flickr.test.login` call afterward that `FLICKR_API_KEY`/`FLICKR_API_SECRET`/OAuth token in `.env` still authenticate unchanged. It was a simple dashboard edit — no re-registration, no new keys. | **Done** |

Posted to issue #61 on 2026-09-02 for tracking:
https://github.com/JennSW/BirdTrip/issues/61#issuecomment-5516888914

---

## 5. Naming decision itself

Not part of this plan's execution scope, but the blocking dependency for
Section 2. See `NAMING_REVIEW.md` for the full candidate history (note:
that file predates the 2026-09-02 session and hasn't been reconciled
with the Perch/coined-word round — front-runner from that later round is
**Perchoto**, checked clean on domain, general web presence, and USPTO
trademark search).

---

## Summary: does the undecided name block anything?

**No.** Sections 2 and 3 don't touch data models, business logic, or API
design — feature work can continue freely. The only thing actually
time-sensitive is Section 1 (the live public portfolio site), which is
independent of when the app itself gets renamed.

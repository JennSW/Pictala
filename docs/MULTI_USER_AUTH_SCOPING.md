# BirdTrip — Multi-User Login: Scope & Level-of-Effort (2026-08-30)

## 1. Ask

Let a second person log into BirdTrip with their own data — their own eBird
checklists, their own Flickr photos, their own matches — without seeing or
touching the other user's data.

## 2. Current state (confirmed by codebase audit)

BirdTrip is explicitly single-user today. `backend/.env.example` says it
outright: *"Nothing in this app is multi-tenant — it's built to hold ONE
person's keys."*

| Area | Current state |
|---|---|
| Database | SQLite (`birdtrip.db`), 5 tables (`checklists`, `observations`, `photos`, `matches`, `sync_log`) — **none have a `user_id` column** |
| Uniqueness | `checklists.submission_id` and `photos.flickr_id` are globally unique — would collide across users as-is |
| Credentials | Flickr OAuth1 token pair + eBird key live as global env vars in `backend/.env`, read directly off a module-level `settings` singleton at request time (`flickr_client.py`) |
| eBird import | CSV upload (user downloads "My Data" from eBird, uploads in-app) — **not** a live API call, so no per-user eBird credential is actually needed |
| Flickr import | OAuth1, currently bootstrapped once via a CLI script (`flickr_oauth_setup.py`) that writes tokens straight into `.env` — no in-app connect flow exists |
| API routes | 22 endpoints across 5 routers, all unscoped — no auth dependency anywhere |
| Frontend | No login UI, no session/token handling, no protected routes |
| Migrations | No Alembic — schema changes go through a hand-rolled `add_missing_columns()` in `db.py`. Its own docstring flags that anything beyond simple additive columns is "the signal to introduce Alembic properly" |

**Bottom line:** this isn't "add a login screen in front of an existing
multi-tenant app" — every layer (DB, credentials, routes, frontend) assumes
exactly one person, so multi-user touches all four.

## 3. Requirements

**In scope**
- Each user has their own account and can only see their own checklists,
  photos, and matches.
- Each user connects their *own* Flickr account (in-app OAuth flow, not a
  shared `.env` token).
- Each user uploads their *own* eBird CSV (already per-upload today —
  mainly needs a `user_id` stamped on the resulting rows).
- Existing single-user data (Jen's) migrates cleanly to "user #1" with zero
  data loss.

**Explicitly out of scope for this pass**
- Public self-service signup ("share with the birding community," backlog
  #17) — that's a distinct, larger feature this work would unblock but not
  build.
- Social login (Google/Apple OAuth) — plain email+password is sufficient
  for a small, known set of users.
- Real-time collaboration or shared/cross-user views.

## 4. Two viable approaches

### Option A — Lightweight, invite-only (recommended)

Password-based login, no self-registration (accounts created manually or
via a one-time invite flag), SQLite stays as-is with `user_id` columns
added. Sized for "a few people I know," not the general public.

### Option B — Production-grade

Everything in A, plus: email verification, password reset flow, rate
limiting on auth endpoints, migration off SQLite to Postgres (needed once
concurrent writers are a real possibility), and hardened session handling.
This is the bar the PRD deliberately excluded from v1 as "production
hardening."

**Recommendation: Option A.** The actual ask is "let one more person log
in," not "launch a public product." Option B's extra cost (Postgres
migration, email infra, password-reset UX) buys security/scale properties
this use case doesn't need yet. Move to B only if/when #17 (public sharing)
gets scoped for real.

## 5. Work breakdown (Option A)

| # | Work item | Notes | Est. |
|---|---|---|---|
| 1 | `users` table + password hashing (bcrypt) | New model, no Alembic needed yet — one additive table | 0.5 day |
| 2 | Session auth (login/logout endpoints, session cookie, `get_current_user` dependency) | Replaces the implicit "there is one user" assumption | 1 day |
| 3 | Add `user_id` FK to `checklists`, `photos`, `matches`, `sync_log` + backfill existing rows to user #1 | `observations` inherits scoping via `checklist_id` FK, no direct column needed. This is the riskiest step — see Risks | 1 day |
| 4 | Fix uniqueness constraints to be composite (`user_id` + `submission_id` / `flickr_id`) | Must land with #3, not after | 0.5 day (included in #3's estimate) |
| 5 | Retrofit all 22 existing endpoints to filter every query by `current_user` | Mechanical but touches every router file | 1.5 days |
| 6 | Per-user Flickr credential storage (encrypted token pair in `users` table or a new `user_credentials` table) | New: today's `flickr_oauth_setup.py` bootstrap script becomes a real in-app "Connect Flickr" OAuth flow | 1.5 days |
| 7 | Frontend: login page, auth context, protected routes, "Connect Flickr" UI | New surface area on a frontend with zero existing auth code | 1.5 days |
| 8 | Manual QA: two-user smoke test (no data bleed, both can sync/match independently) | | 0.5 day |

**Total: ~8 engineer-days** (compressed further with AI-assisted
development, per this project's actual pace — recent features like the
in-app eBird CSV upload landed same-day).

## 6. Risks & open decisions

- **Data migration (#3) is the one step with real blast radius** — it
  touches every row in every table. Needs a tested backfill script and a
  DB backup taken immediately before running it, not just "add the
  column and hope."
- **Flickr's OAuth1 app credentials (`flickr_api_key`/`secret`) are
  currently per-*app*, not per-user** — that part stays global; only the
  per-user *token pair* changes. Confirm this is still true when building
  #6 — Flickr's OAuth1 flow ties tokens to the app's consumer key.
- **Decision needed before starting:** is SQLite acceptable long-term
  for 2+ concurrent users, or is this the moment to plan the Postgres
  move anyway (even if not executed now)? Recommend deferring — SQLite
  handles a handful of low-frequency users fine; revisit if #17 ever gets
  scoped.
- **Decision needed before starting:** how are new accounts created —
  manual DB insert by Jen, a CLI script, or a minimal invite-code flow?
  Affects #2's scope slightly. Recommend a CLI script (`create_user.py`)
  to start; it's the cheapest option that isn't a raw DB insert.

## 7. Sequencing

Do #1 → #3/#4 → #2 → #5 → #6 → #7 → #8, in that order. #3 (the data
migration) should land early and get lived-with for a bit before piling
more code on top of a reshaped schema — the other steps depend on it
existing but not on it being "final."

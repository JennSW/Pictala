# BirdTrip — Program Status Report

> Where this document cites an issue by number, it refers to the project's [issues board](https://github.com/JennSW/Pictala/issues).

**Date:** 2026-08-30 · **Audience:** Cross-functional stakeholders (Product, Engineering, Legal, Trust & Safety) · **Program:** v2 — Multi-User & Community Sharing

## Done

- **v1 shipped and stable.** Core matching flow (eBird checklist ↔ Flickr
  photo, AI-assisted species suggestion) is in daily production use.
- **Recent hardening (past 3 sessions):** in-app eBird CSV upload (closes
  #49), same-day fallback matching fixed to run per-photo instead of
  per-checklist (closes #59), a batch of label/first-use UX fixes (#41,
  #56, #57, #58), and a mobile viewport/accessibility audit fix.
- **Backlog groomed** ([BACKLOG_SCOPING.md](BACKLOG_SCOPING.md)) —
  everything beyond v1 is now sorted by actual buildability, not just
  board position.
- **Phase 1 scoped today:** multi-user auth level-of-effort complete
  ([MULTI_USER_AUTH_SCOPING.md](MULTI_USER_AUTH_SCOPING.md)) — codebase
  audited (zero existing auth scaffolding confirmed), two approaches
  compared, lightweight/invite-only recommended, ~8 engineer-days
  estimated across 8 work items.
- **API surface documented** ([API_DOCUMENTATION.md](API_DOCUMENTATION.md))
  — 24 endpoints across 6 resource groups, written for both engineering
  and non-engineering review (Legal/Trust & Safety data-handling notes
  included).

## Next

- Get sign-off on the two open decisions blocking Phase 1 start (see
  Decisions below).
- Kick off Phase 1 work item #1 (users table + password hashing) once
  decisions land — no code has started yet, this is still pre-build.
- Trust & Safety and Legal review of the Program Charter's Phase 1 design
  before engineering begins, since Phase 1's credential-isolation
  approach is the foundation Phase 2 (community sharing) will need to
  build moderation on top of.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Data migration (adding `user_id` to 5 tables + backfilling existing data) touches every row in every table | Medium | High | Tested backfill script + full DB backup immediately before running; done first and lived-with before more code lands on top |
| Flickr OAuth1 app-vs-user credential boundary not yet confirmed | Low | Medium | Confirm against Flickr's actual OAuth1 flow before finalizing credential-storage design (work item #6) |
| Scope creep toward Phase 2 (sharing) during Phase 1 build | Medium | Medium | Explicitly rejected in the charter; Phase 2 requires its own charter and T&S/Legal review before any code |

## Decisions needed (blocking Phase 1 start)

1. **Account creation method** — manual DB insert, CLI script, or a
   minimal invite-code flow? Recommendation: a CLI script (`create_user.py`)
   as the cheapest option that isn't a raw DB insert.
2. **SQLite vs. Postgres timing** — stay on SQLite for Phase 1 (handles a
   handful of low-frequency users fine) and revisit only if/when Phase 2
   gets scoped? Recommendation: defer.

Both decisions are Product's call; Engineering has a recommendation on
each but is not blocking on being right, just on being decided.

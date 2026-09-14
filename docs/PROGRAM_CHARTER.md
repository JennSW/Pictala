# Program Charter — BirdTrip v2: Multi-User & Community Sharing

**Status:** Draft for review · **Date:** 2026-08-30 · **Program Lead:** Jen Swift

## 1. Purpose

BirdTrip v1 shipped as a personal tool: one person's eBird checklists,
matched automatically against their own Flickr photos. It works, and it's
in daily use. The next horizon — already flagged in the backlog as
**#16 (multi-user support)** and **#17 (share with the birding
community)** — is turning it into something other birders can use, and
eventually a place sightings and photos can be shared *between* birders,
not just organized for one.

This charter scopes that transition as a single program with two phases,
because #17 cannot be scoped or resourced honestly until #16's foundation
— real accounts, isolated data, secure per-user credentials — exists
under it.

## 2. Objectives (OKRs)

**Objective: Prove BirdTrip works for more than one person, safely.**

- KR1: A second real user can log in, sync their own eBird/Flickr data,
  and review matches with zero visibility into the first user's data.
- KR2: Each user connects their own Flickr account via an in-app OAuth
  flow — no shared credentials in a config file.
- KR3: Zero data-isolation defects found in two-user QA before this phase
  is called done.

**Objective (Phase 2, not yet resourced): Make sharing feel safe, not
risky.**

- KR1: A content-moderation and reporting path exists before any
  cross-user visibility ships.
- KR2: Legal sign-off obtained on photo attribution/copyright handling
  for shared content.

## 3. Scope

**Phase 1 — Multi-user foundation (this program's committed scope)**
- Per-user accounts, session auth, data isolation across all 5 DB tables.
- Per-user Flickr OAuth connection flow (replacing the current one-time
  CLI bootstrap script).
- Migration of existing single-user data with zero loss.

**Phase 2 — Community sharing (scoped separately, gated on Phase 1)**
- Cross-user visibility into shared sightings/photos.
- Moderation, reporting, and privacy controls.
- Not committed in this charter — listed here only to show why Phase 1's
  design decisions (e.g. per-user credential storage, not a shared
  secret) are made with Phase 2 in mind.

**Explicitly out of scope**
- Public self-service signup (Phase 1 is invite-only).
- Social login / SSO.
- Real-time collaboration features.

## 4. Timeline

See [Program Toolkit — Milestone Chart](#) for the visual version. Phase 1
target: **~2 weeks elapsed** (≈8 engineer-days of work, per
[MULTI_USER_AUTH_SCOPING.md](MULTI_USER_AUTH_SCOPING.md)), sequenced as:

1. Data model + migration (highest-risk step, done first, lived-with
   before more code lands on top)
2. Session auth
3. Endpoint retrofit (all 23 routes scoped to the current user)
4. Per-user Flickr OAuth connect flow
5. Frontend login + protected routes
6. Two-user QA pass

## 5. Stakeholders & resourcing

| Stakeholder | Role in this program |
|---|---|
| **Engineering** | Builds all of Phase 1; single-threaded (this is a small project), AI-paired |
| **Product** | Owns scope calls: invite-flow design, what "Phase 2 ready" means |
| **Legal** | Reviews credential-storage approach (encrypted Flickr tokens) and, ahead of Phase 2, photo copyright/attribution when content becomes cross-user visible |
| **Trust & Safety** | Not load-bearing in Phase 1 (no cross-user visibility yet) — but must review Phase 1's design *now*, since account security and credential isolation are exactly what Phase 2's moderation model will sit on top of |
| **Marketing / Community** | No Phase 1 deliverable; consulted on what "invite-only" onboarding should feel like, since it's the seed of Phase 2's community framing |

Full detail in the [RACI matrix](#) and [dependency map](#).

## 6. Risks & dependencies

Top risks (full register in the [Program Toolkit](#)):
- **Data migration blast radius** — touches every row in every table;
  mitigated by a tested backfill script + pre-migration backup, not a
  live edit.
- **Flickr OAuth1 app-vs-user credential boundary** — the app's consumer
  key stays shared; only the token *pair* becomes per-user. Needs
  confirmation against Flickr's actual OAuth1 flow before Phase 1's
  credential-storage design is finalized.
- **Scope creep toward Phase 2** — the temptation to "just add sharing
  while we're in the auth code" is real and explicitly rejected here;
  Phase 2 needs its own charter once Trust & Safety and Legal have
  reviewed Phase 1's foundation.

## 7. Success criteria

Phase 1 is done when: a second user account exists, has synced its own
data independently, shows zero cross-contamination with user #1's data in
QA, and the original single-user data is intact and correctly attributed
to user #1 post-migration.

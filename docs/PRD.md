# Pictala (formerly BirdTrip) — PRD

## 1. Problem Statement

Bird photographers juggle three disconnected apps to make sense of a
single outing: an eBird checklist (species, time, location), a photo host
like Flickr (photos, loosely timestamped), and Merlin (Cornell's ID app,
used separately to identify a bird from a photo, or a call from an audio
recording). None of the three links to another — reconstructing "what did
I photograph on this walk" means manually cross-referencing all three by
hand.

Pictala bridges the photo host and the eBird checklist for the same day,
so a single app shows your own photos next to what bird is actually in
each one — common name and scientific name. Its AI-assisted matching
search (Strategy B / "Ask Claude," see `DESIGN.md`) already does visual
species identification directly from the photo, standing in for the
photo-ID half of that separate trip to Merlin. Merlin's audio-recording
ID is a distinct, still out-of-scope case, tracked separately (Section 4,
"Merlin recordings").

Separately, this project exists as a demonstration piece: a small,
well-scoped problem that surfaces real system-design decisions — two APIs
with different auth models, a matching problem with no shared key, and a
defensible judgment call about where AI belongs versus where deterministic
rules are the better tool.

## 2. Goals & Success Criteria

**Primary (portfolio):**
- The codebase and its documented tradeoffs (rule-based-vs-AI,
  deterministic-first ordering, confidence-scored AI suggestions) hold up
  under technical questioning in an interview setting.
- The project is small enough to walk through end-to-end in a live demo,
  but touches enough real engineering judgment to sustain a substantive
  conversation.
- Wireframes of the core user experience are available to walk through in
  a demo — showing how a customer would actually use the app, and the
  reasoning behind key UX decisions (e.g. why review/approve exists, why
  saving locks a day). *Status (2026-10-14): as built, marking an outing
  reviewed does not lock it (see Section 4).*

**Secondary (personal use):**
- The app is genuinely usable on your own outings without friction — sync,
  review, and save for a day's results should be fast enough that you
  actually do it, not just could.
- When the two goals conflict, the portfolio narrative wins — but most of
  what we're building (automation, review UX) serves both at once, so
  conflicts should be rare.

**Future (V2) — not a v1 goal:**
- Share Pictala with others in the birding community. This is a vision
  item, not something v1 is scoped or evaluated against — it only becomes
  realistic once the app is functionally solid and presentable. Related
  technical enabler (multi-user support: letting others add their own
  Flickr/Merlin user IDs) is already noted in `BRAINSTORMING.md`.
  Not revenue-focused — likely to remain freeware.

**Non-goal as a success criterion:** this isn't measured by number of
users, uptime, or growth — it's a single-user tool evaluated on demo
quality and your own real usage.

## 3. Target Audience

Two distinct groups, with different things they need to see:

**1. Interview demo audience.** A senior-level Product Manager embedded in
a technical team or technical organization. The session is a technical
review — expect scrutiny of the engineering decisions (why rules before
AI, how the matching problem was solved) *and* a discussion of why
specific UX decisions were made (this is what the wireframes goal in
Section 2 is for — being able to walk through the customer experience and
defend the reasoning behind it, not just the code).

**2. Select group of birders.** Bird photographers who also keep an eBird
checklist — the same person wants both the rigor of a data-driven list
and the reward of a great shot. Data-lover and creative at once:
analytical enough to log a checklist, moved enough by a good sighting to
stop and photograph it. They already publish to a photo host and enjoy
showing photos to other photographers/birders in the field — the
motivating case behind the "Sharing a photo in the field" scenario and
Search by species story in Section 5, not a separate unscoped ask.

Some technical savvy, but low tolerance for effort — they want it to
work, not to debug it. This group is shared with deliberately narrowly
(not general public) and shouldn't need
ongoing support from me to use it. This is the audience the V2 "share
with the birding community" goal (Section 2) and the V2 multi-user
support idea (`BRAINSTORMING.md`) are ultimately for — though for v1,
"shouldn't need support" is itself a real constraint worth carrying into
Scope & Non-Goals and Assumptions (e.g. it argues against a local
git-clone-and-run setup as the sharing mechanism).

*Status (2026-10-14): v1 as published is a local clone-and-run (`start.sh`), and it expects
you to bring your own Flickr and eBird accounts. Sharing with this group stays a V2 goal.*

## 4. Scope & Non-Goals

**In scope for v1:**
- eBird checklist ingestion **by file upload only**: the Download-My-Data CSV, or the
  zip eBird emails. eBird has no API for your own history, so uploading is the one way
  eBird data enters the app (`DESIGN.md` section 7). Flickr photos come in by API sync.
- Rule-based matching (Strategy A) and AI-assisted species suggestion for
  uncaptioned photos (Strategy B), per `DESIGN.md`.
- The review workflow from the brainstorm notes, as built: a results page per outing;
  confirm, reject or edit a photo's species, assign one by hand, or move a photo to
  another group; flag a photo as not a bird; optional notes on a photo; and mark an
  outing reviewed. Marking reviewed is a stored flag, available once every photo is
  confirmed and reversible with Unmark. It does not lock the outing: edits and syncs
  still apply.
- Wireframes of the core experience, for the interview demo audience.
- Single-user only (you) — your own API keys/credentials, local data.
- Each photo links to its original Flickr display page (not just the
  raw `.jpg`), so a viewer can click through to see it on Flickr itself.
- **Accessibility compliant, usable by screen readers.** Applies to the
  whole UI, not just photos. *Status (2026-10-14): done. The standing
  rule is in `DESIGN.md` section 10.5; photos carry alt text (their title)
  in the viewer, and the accessibility and mobile work is closed on the
  board.*
- **Webpage for now** — usable on desktop, with a mobile layout. Not a
  native app.

**Out of scope for v1 (deferred to V2):**
- Additional photo hosting sites beyond Flickr (e.g. SmugMug) —
  `BRAINSTORMING.md`.
- Merlin recordings — `BRAINSTORMING.md`.
- Multi-user support (others adding their own Flickr/Merlin IDs) —
  `BRAINSTORMING.md`.
- Sharing/hosting for the select-group audience, and any deployment work
  that implies (e.g. moving off local-only, off SQLite) — tied to the V2
  "share with the birding community" goal, not v1.
- Revenue generation of any kind — likely to remain freeware
  (Section 2).
- Production hardening generally (auth beyond a single user, a
  non-SQLite database) — `DESIGN.md` already calls this a deliberate
  scope boundary.

**Resolved decision: matching strategy is hybrid.** Checklist-first stays
the default (cheap, accurate, matches the `DESIGN.md` "rules first, AI for
the residual" narrative) — Claude-first identification only runs as a
fallback for photos with no matching checklist at all. Rationale beyond
the accuracy/cost tradeoff: this keeps Claude's use in the app looking
like a deliberate, narrow engineering decision rather than something
forced in to check an "I used AI" box — it shows up exactly where a
constrained/deterministic approach genuinely can't reach, which is a
stronger interview story than AI-everywhere. This extends (not replaces)
the Strategy B "AI suggest" behavior already described in `DESIGN.md`.

**Still open (tracked, not decided here):** nothing at the moment.

*Resolved 2026-10-14: an outing marked reviewed can be reopened with
Unmark.*

## 5. Key Use Cases

Narrative scenarios — detailed acceptance criteria live in
`USER_STORIES.md`, not duplicated here.

**Sharing a photo in the field.** I'm out birding with friends, comparing
life lists on eBird. I want to share a photo I took of a specific bird on
the day I saw it. I open Pictala, search for the bird by name from the
home screen, and the search result shows the date and the matching photo.

These became two stories in `USER_STORIES.md`, both now built:
- **Search by species** — find a photo by bird name rather than browsing
  outings one at a time.
- **Date selection** — a way to narrow results by date. Details TBD.

**Interview screening call.** I'm on a screening call with a hiring
manager. She asks what I've been working on, and I demo Pictala —
screen-sharing the running app and also sharing the GitHub repo directly.
She asks technical and UX tradeoff questions.

This doesn't introduce new stories — it's the scenario the interview-demo
goals already exist for (wireframes, documented tradeoffs in `DESIGN.md`,
a repo clean enough to hand someone a link to). It does mean the repo
itself is part of the deliverable, not just the running app: README
quality, commit history, and not having anything in there that undercuts
the narrative (already a live concern).

## 6. Assumptions & Constraints

*(not yet drafted)*

## 7. Open Questions / Risks

*(not yet drafted)*

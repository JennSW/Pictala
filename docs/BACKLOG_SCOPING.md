# BirdTrip — Backlog & V2 Scoping (2026-08-12)

A snapshot review of everything open on the board beyond v1 (now fully closed
per `docs/PRD.md` §4) — organized by actual readiness to build, not just
board bucket, since a few "V2"-labeled items are trivial and a few
small-looking items are blocked on decisions rather than effort. Written to
pick the conversation back up in a future session, not acted on yet.

## Ready to build now (no decision needed first)

**#53 — Self-host Public Sans.** Mechanical swap: `@fontsource/public-sans`
npm package instead of the Google Fonts CDN. No design call, no
dependencies, no risk. The single easiest pickup on the whole list.

## One quick decision away from trivial

**#52 — Icon color reconciliation.** The eBird-match icon colors
(lavender/peach) are close to two colors the confirmed brand palette
dropped. Jen's earlier reasoning was that badge icons need to contrast
against photo content, a different goal than UI chrome — so this may be an
intentional exception, not a bug. Needs one call: leave as exception, or
pick new colors from the Brand Book. Either way, the code change afterward
is trivial.

**#34 — Defect: photo counts undercount on bad `date_taken`.** Real,
verified bug (Smith Island: 32 real photos, only 1 counted) — root cause is
confirmed (a Flickr metadata export artifact, not a matcher bug). Needs a
product decision before any code: should matching ever fall back to
tag/text evidence when the date doesn't align, or is this purely a
"fix the data at the source" problem? Once decided, the fix itself is
small-to-medium.

## Needs real scoping before it's buildable

**#51 — Right-rail on entry screen.** Explicitly flagged as a rough
placeholder in the mockup — what actually belongs there (account links?
downloads? settings?) was never decided, just sketched. This is a
product-decision task first, a small UI task second.

**#54 — Real "new since last visit" greeting.** Bigger than it looks:
there's no "last visited" concept in the backend at all today
(`reviewed_at` means something different — fully resolved, not just seen).
Needs actual new schema/semantics, not just wiring up existing data like
the rest of the entry-screen work was.

**#9 — Manual override for outing grouping.** Never turned into a real
story — just a raised question. Needs scoping (what does a manual
split/merge UI even look like?) before it's buildable. Worth doing if
automatic grouping is actually misfiring in practice; otherwise low
urgency.

**#50 — Batching (bulk approve/confirm, bulk Ask Claude).** Flagged
previously as UI-decision-heavy. Needs a real UX pass on selection
semantics before build — one of the bigger backlog items in design work,
not huge in code once scoped.

## Real architectural debt, not a quick pickup

**#45 — No client-side routing.** Confirmed root cause: zero URL state, so
back/forward/reload always hard-resets. Real fix means adding react-router
and restructuring how OutingDetail/ClusterDetail load (route param instead
of click handler) — a genuine multi-hour lift, not a tweak. Worth doing
before the app gets meaningfully bigger, since it only gets more invasive
to retrofit later.

## The big vision items (not independently actionable yet)

**#16 — Multi-user support** and **#17 — Share with the birding community**
are coupled: #17 is a vision statement, not a scoped feature, and it
depends on #16, which itself means real auth, per-user credential storage,
and moving off local-only SQLite — explicitly the "production hardening"
the PRD deliberately excluded from v1. Neither is a "pick back up for an
afternoon" item; they need their own dedicated scoping session before any
code starts.

## Research-stage, not yet scoped (V3 / investigation)

**#14** (SmugMug/other photo hosts) and **#15** (Merlin recordings) are both
"investigate feasibility" tickets — no confirmed technical path yet, not
buildable as-is. **#20** (post-to-Flickr for missing matches) and **#21**
(map view) are both explicitly captured as V3 and unscoped; #21's data
layer is actually ready (lat/lon already flows through), so it's the
cheaper of the two once someone decides to scope it.

## Not app work

**#38 — Flickr data clean-up** is entirely manual housekeeping (correcting
wrong dates on ~5 specific photo batches directly on Flickr, checking the
camera's clock) — zero code involved, doesn't belong on a dev-session
backlog at all. **#19** (private-docs directory decision) is a repo-
organization call, not a feature.

## Recommendation for next session

- **Quick, satisfying session:** #53 → #52 → #34 — one trivial fix, one
  quick-decision-then-trivial fix, and one real (if small) bug fix, all
  completable without a big design conversation first.
- **Meatier forward progress:** #45 (routing) is the best-scoped "real"
  item on the list and only gets more expensive to add later — it's
  infrastructure, not a feature, but it's blocking cleanly.
- **Toward the V2 vision rather than just clearing the board:** #16/#17
  need a dedicated scoping conversation before anything else — they're the
  actual next milestone after v1, but nothing else in the backlog
  meaningfully advances them.

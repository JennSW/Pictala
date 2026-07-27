# BirdTrip — User Stories

Backlog of user-facing stories, grouped by feature area. Each story follows:
**As a / I want / so that** → Description → Acceptance Criteria → Priority → Notes.

Shared behavioral rules that would otherwise bloat every story that touches
them live in a "Functional Spec" block above the relevant story group, and
individual stories reference it rather than repeating it.

---

## Feature: Sync (eBird + Flickr)

### Functional Spec: Sync behavior

- Two trigger types: **automatic** (fires on outings-page load) and
  **manual** (a "Sync now" button).
- Independent daily budgets: automatic = 1x/day, manual = 4x/day. Budgets do
  not share a pool.
- "Day" means a **calendar day in the user's own time zone** (resets at
  midnight local time, not UTC or the server's time zone) — not a rolling
  24-hour window.
- Every attempt counts toward its budget regardless of success or failure.
- A sync (of either type) covers today plus any unsynced, *unsaved* days
  since the last successful sync.
- Any day whose results have already been saved/locked (see *Save results*
  story) is always skipped by sync, regardless of trigger type — this is
  how saved results are protected from being overwritten.
- eBird retrieval: the regional checklist-feed endpoint
  (`/product/lists/{regionCode}/{y}/{m}/{d}`), filtered to a configured
  eBird display name (no direct "my checklists" API exists). Flickr
  retrieval: existing date-range sync, unchanged.
- Requires one-time setup: eBird display name, region code(s), and the
  user's time zone (for calendar-day resets), following the same pattern
  as the existing `.env`-based API keys.
- Rate-limit and last-synced state must persist across app restarts (not
  in-memory only).
- Original bulk-history CSV import is unaffected — this spec only covers
  ongoing, day-to-day updates.

### Story: Manual sync

**As a** birder, **I want** a manual "Sync now" button I can use up to 4
times a day, **so that** I can pull in fresh results right after I finish
uploading photos to Flickr, without waiting for the next automatic sync.

**Acceptance Criteria:**
- Given fewer than 4 manual syncs have occurred today, when I click "Sync
  now," then a sync runs immediately per the Sync behavior spec.
- Given 4 manual syncs have already occurred today, then the button is
  disabled and shows when it becomes available again.

**Priority:** High

---

### Story: Automatic sync on page load

**As a** birder, **I want** the app to automatically check for new eBird
and Flickr data once a day when I open it, **so that** I don't have to
remember to sync manually just to see current results.

**Acceptance Criteria:**
- Given the automatic sync hasn't run yet today, when the outings page
  loads, then a sync runs automatically per the Sync behavior spec.
- Given the automatic sync has already run today, when the page loads
  again, then no sync runs, and the page shows the last-synced time.

**Priority:** High

---

### Story: Sync never overwrites saved days

**As a** birder, **I want** a day's results to stay exactly as I saved
them, **so that** a later sync can never quietly change or overwrite my
finalized review.

**Acceptance Criteria:**
- Given a day's results have been saved/locked, when any sync runs (auto
  or manual), then that day is excluded entirely — no checklist or photo
  data is re-pulled for it.

**Priority:** High

**Notes:**
- Depends on the *Save results* story (not yet drafted) for what "saved"
  means.
- Open question, not yet resolved: if new photos surface for an
  already-saved day, there's currently no way to reopen/unlock it. Revisit
  when drafting *Save results*.

---

## Feature: Species identification

*(not yet drafted)*

## Feature: Results review (edit, approve, flag, save)

*(not yet drafted)*

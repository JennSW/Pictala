# Code Review: Hallucination Audit — 2026-09-04

> **Correction (2026-09-04):** the issue numbers below were originally
> wrong due to a bug in the bulk issue-creation script — each filed issue's
> title/labels ended up paired with the wrong finding's body (one slot off).
> Titles, labels, and this table have all been corrected to match; #82 is
> the real "accept_suggestion" finding (was mistakenly closed as a
> duplicate, now reopened), and #81 was closed as a genuine duplicate of
> #83 once the mislabeling was fixed.

**Trigger:** two confirmed Claude hallucination incidents on 2026-09-03 (see
[`CLAUDE_ERROR_LOG.md`](CLAUDE_ERROR_LOG.md)) prompted a broader question —
did earlier sessions hallucinate anything into the actual codebase or docs,
not just into chat narration? This review covers all work committed on or
before 2026-09-02. The 2026-09-03 commits were already scrutinized in the
session that produced the error log and were only skimmed here.

**Method:** three independent review passes (backend, frontend, docs), each
required to verify claims rather than just read code — running the real
test suite, checking library calls against actually-installed package
signatures, tracing every frontend API call against the real backend route,
and checking every "closes #N" / "committed as `<hash>`" / test-count claim
in the docs against actual git history.

## Verdict

**No confirmed hallucinations found in code or documentation from before
2026-09-03.** Specifically:

- Zero fabricated library/API calls (checked every third-party call in the
  backend against `inspect.signature` on the actually-installed package, and
  every frontend library/hook usage against the installed package's own type
  definitions).
- Zero fabricated backend routes referenced by the frontend — all 22
  `api.ts` functions trace to a real route with matching method, path, and
  request/response shape.
- Zero hollow/tautological tests. All 17 backend tests assert specific,
  non-trivial outcomes.
- Zero functions defined but never called anywhere.
- Two numeric claims in session-recap docs ("16/16 tests pass", "17/17
  tests pass") were independently recounted against the actual test files
  at that exact commit and matched exactly.
- Every "closes #N" / "committed as `<hash>`" claim spot-checked against
  `git log` matched the real commit and diff.

This is a materially different result from the two 2026-09-03 incidents —
those look like a session-specific narrative lapse, not a pattern running
through the codebase or its documentation.

What the review did find: a handful of real bugs, a real test-coverage gap,
and some stale (not fabricated) documentation. Each is filed as its own
issue on the [BirdTrip project board](https://github.com/users/JennSW/projects/1),
linked below.

## Findings

### Backend

Scope: `backend/app/{main,config,db,models,schemas}.py`, `routers/*.py`,
`services/*.py`, `tests/*.py`. Verified by running
`pytest -v` (17 passed, 0 failed), checking every third-party call
(`TimezoneFinder`, SQLAlchemy `Inspector`/`Index`/`TypeEngine`,
`requests_oauthlib` `OAuth1`/`OAuth1Session`, FastAPI/pydantic) against the
installed library via `inspect.signature`, and tracing call sites for every
non-trivial service function via `grep`.

| Severity | Finding | Issue |
|---|---|---|
| Medium | `accept_suggestion` writes an unvalidated `observation_id` with no checklist-group check, unlike its sibling `assign_species` | [#82](https://github.com/JennSW/BirdTrip/issues/82) |
| Medium | `guess_species` candidate-name comparison is case-sensitive; every other name-matching path in the codebase is case-insensitive | [#73](https://github.com/JennSW/BirdTrip/issues/73) |
| Low | ~2/3 of the service layer (`outing_grouping`, `outing_review`, `photo_clusters`, `timezone_check`, `ebird_import`, `flickr_client`, `flickr_exif`, and `species_classifier`'s guess-parsing) has zero automated tests | [#74](https://github.com/JennSW/BirdTrip/issues/74) |
| Low | `duplicate_detection.py`'s docstring asserts a specific "verified against live data on 2026-08-06: exactly 4 groups" result with no corroborating fixture — matches the pattern in the error log (a claim asserted without durable evidence), though the *algorithm* itself is genuinely well-tested | [#75](https://github.com/JennSW/BirdTrip/issues/75) |

Positive: the rule-based matcher and duplicate-detection heuristic are
unusually well documented, with docstrings that explain *why* (including
rejected earlier approaches) and tests that encode real historical
regressions (e.g. issue #59). Every docstring cross-checked against its
implementation, other than the one flagged above, accurately described real
behavior.

### Frontend

Scope: `frontend/src/*.tsx`, `*.ts`, `package.json`. Verified by
cross-referencing all 22 `api.ts` calls against the real backend routes and
Pydantic schemas, checking `react-day-picker`/`date-fns` usage against the
installed packages' own type definitions, and using `git log -S` to date
each finding's origin.

| Severity | Finding | Issue |
|---|---|---|
| Medium | Fallback UI shows "Not a bird" whenever `is_other` is true, but the backend's own `resolve_guess()` documents that `is_other` covers two distinct cases (not a bird, or a bird the taxonomy didn't recognize) — the frontend never checks the `is_bird` field it already has. Introduced 2026-07-31 (`a117249`). | [#76](https://github.com/JennSW/BirdTrip/issues/76) |
| Medium | Batch "confirm" and batch "Ask Claude" share one `MAX_BATCH_PHOTOS` (10) selection cap counted across the whole outing instead of each action's own eligible set — checking 10 boxes for one action blocks the other. No data corruption (each handler still filters to its own subset). Widened 2026-09-03 (`fdd5f12`) on top of an existing 2026-08-11 pattern. | [#77](https://github.com/JennSW/BirdTrip/issues/77) |
| Low | The fallback "Actually on this checklist" hint is computed from the AI's original guess text, not the (possibly edited) text about to be saved — advisory copy only, the actual save re-resolves correctly server-side | [#78](https://github.com/JennSW/BirdTrip/issues/78) |
| Low (disclosed) | Note text typed when assigning a *real* species (not a fallback) is silently discarded — already flagged in-code as "not yet wired up", filed for backlog visibility | [#79](https://github.com/JennSW/BirdTrip/issues/79) |

Positive: comments throughout `App.tsx` accurately describe what the code
does; doc citations to `DESIGN.md` section numbers all resolve to real
sections; no fabricated endpoint calls or invented library APIs found
anywhere in the frontend.

### Documentation

Scope: `API_DOCUMENTATION.md`, `DESIGN.md`, `PRD.md`,
`MULTI_USER_AUTH_SCOPING.md`, `USER_STORIES.md`, `BACKLOG_SCOPING.md`,
`PROGRAM_CHARTER.md`, `PROCESS_RETROSPECTIVE.md`, `STATUS_REPORT_2026-08-30.md`,
and a representative sample of dated `README-*.md` session recaps.

| Severity | Finding | Issue |
|---|---|---|
| Medium | `API_DOCUMENTATION.md` states "there is deliberately no `/reject` endpoint" — but `POST /match/{checklist_id}/reject/{photo_id}` exists and is used. Doc was accurate when written (its only commit predates `/reject` by weeks); also missing the `/stats` router entirely. Stale, not fabricated. | [#80](https://github.com/JennSW/BirdTrip/issues/80) |
| Low | `MULTI_USER_AUTH_SCOPING.md` and `PROGRAM_CHARTER.md` both say "22 endpoints"; actual count at the commit both were written is 23. Copy-pasted miscount, doesn't misrepresent what's built. | [#83](https://github.com/JennSW/BirdTrip/issues/83) |

**Explicitly not flagged as false:** GitHub issue numbers referenced in
recap docs (no GitHub access from the review environment to confirm the
issue itself, though every paired commit hash/message checked out); the
"in daily production use" claim in the status report (a usage-frequency
claim, not observable from the repo); the API-key-incident note in
`PROCESS_RETROSPECTIVE.md` (plausible, consistent with `.env` being
gitignored, but not independently verifiable). These are unverifiable, not
disproven.

## Recommendations, in priority order

1. Fix the two Medium backend issues (validation gap, case-sensitivity bug) — both are small, isolated changes.
2. Fix the two Medium frontend issues (fallback copy, batch cap scoping) — both are user-facing.
3. Update `API_DOCUMENTATION.md` for `/reject` and `/stats`.
4. Backfill tests for the untested pure-function service modules.
5. Everything else (Low severity) can be picked up opportunistically.

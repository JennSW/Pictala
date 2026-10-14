# Pictala — Architecture and design decisions

> Where this document cites an issue by number, it refers to the project's [issues board](https://github.com/JennSW/Pictala/issues).

A short account of **why Pictala is built the way it is**. Each decision gives what was
chosen, the reason, what it costs, and where to see it. It summarizes
[`DESIGN.md`](DESIGN.md), the dated session recaps in [`Read Me/`](Read%20Me/) and the code, and it does
not replace them. The diagram this document explains is in [`DESIGN.md` §5](DESIGN.md).

The one idea behind most of these choices: **use the simplest thing that is correct, keep a
person in charge of anything uncertain, and say plainly what was left out.**

## 1. Rules first, AI only for what is left over

- **Decision.** Photos are matched to outings and species by deterministic rules. The AI is
  asked about only the photos the rules cannot place.
- **Why.** Joining a photo to an outing is a well-defined problem. Rules are free per photo,
  explainable in a sentence, and easy to test. The open-ended part, naming a bird in a photo
  with no caption, is the only place a model earns its cost. Chosen on 2026-07-28 ("checklist
  first; AI only as a fallback"), because the AI's role should read as a deliberate, narrow
  engineering decision, not a checkbox.
- **Cost.** Rules fail quietly when a camera clock is wrong. That produced two later fixes: a
  same-day fallback applied per photo (#59) and using the date in a photo's title when Flickr only has
  an upload date (#34).
- **See.** [`matcher.py`](../backend/app/services/matcher.py), [DESIGN §4 and §9](DESIGN.md),
  [recap 2026-07-28](Read%20Me/README-2026-07-28-1318.md).

## 2. The AI only suggests, is boxed in, and a person decides

- **Decision.** When the AI is used, it is limited to the species reported on that outing
  (turning "what bird is this?" into a pick among about five to fifteen), returns a confidence
  and a short reason, and nothing is accepted until the user confirms, corrects or sets it aside.
  A photo that matches no checklist species can get a broader guess, which is checked against
  eBird's species list. Every suggestion and its outcome is logged.
- **Why.** A constrained, reviewable suggestion is cheap to check and safe to be wrong. The log
  makes accuracy measurable (`GET /stats/ai-accuracy`) instead of assumed.
- **Cost.** One model call per photo, and a key. So AI suggestions are optional: the app works
  without a key, and the error message says how to add one.
- **See.** [`species_classifier.py`](../backend/app/services/species_classifier.py),
  [fallback flow](diagrams/fallback-identification-flow.svg),
  [species-matching flow](diagrams/species-matching-flow.svg).

## 3. eBird data comes in as a file, not through the API

- **Decision.** Checklists are imported from eBird's "Download My Data" export (the CSV, or the
  zip eBird emails). The eBird API is used only to look up species names.
- **Why.** eBird has no "my own history" endpoint, so the export is the practical route to a
  personal history ([DESIGN §7](DESIGN.md)).
- **Consequence.** The export is cumulative, so re-importing is the normal case, not an edge
  case. A re-import must not erase the species matches a person already confirmed. A defect that
  did exactly that was found on 2026-09-19 (#95) and fixed on 2026-10-13: confirmed links are
  remembered and restored. The upload also accepts the .zip as emailed, since that is what people
  have.
- **See.** [`ebird_import.py`](../backend/app/services/ebird_import.py).

## 4. Flickr is pulled for your own account, and never partially

- **Decision.** One-time OAuth 1.0a authorization for your own account, then photos are fetched
  by date range, following every page of results. A range too large to fetch completely is refused
  with a message to narrow it.
- **Why.** Reading only your own photos needs no login system. A silently truncated list is worse
  than an error: the first version asked for 500 photos and never requested the second page.
- **See.** [`flickr_client.py`](../backend/app/services/flickr_client.py) (500 photos per page,
  at most 20 pages).

## 5. Local, one user, one SQLite file

- **Decision.** Everything runs on the user's own machine, with their own keys and a local
  database. There is no hosted version.
- **Why.** It kept the scope honest, and it means the app never touches anyone else's
  credentials. Going multi-user is a separate program, blocked on three decisions: how accounts are
  created, SQLite versus Postgres, and hosting. Hosting was found to be required in every scenario
  on 2026-09-19 ([recap](Read%20Me/README-2026-09-19-1328.md)).
- **Cost.** Each person brings their own Flickr and eBird accounts, and there is no hosted demo.
- **See.** [DESIGN §5 and §6](DESIGN.md), [`MULTI_USER_AUTH_SCOPING.md`](MULTI_USER_AUTH_SCOPING.md).

## 6. One table for the current state, a separate log for history

- **Decision.** `Match` holds only the current link between a photo and a checklist or species.
  `AiSuggestionLog` records every AI suggestion and its outcome and deliberately has no foreign key
  to `Match`.
- **Why.** If a rejected or edited suggestion overwrote the match, it would leave no trace, and
  there would be nothing to measure accuracy against.
- **See.** [DESIGN §5a](DESIGN.md), [data model diagram](diagrams/data-model.svg).

## 7. The database refuses bad data, not only the code

- **Decision.** SQLite is told to enforce foreign keys on every connection, and the match
  endpoints reject a photo id that does not exist (HTTP 404) before writing anything.
- **Why.** A code review on 2026-10-13 found that one request with an unknown photo id returned an
  error and still saved a match pointing at nothing. After that, the outing page failed permanently.
  Checking in the handler and in the database means a missed check in one place is not fatal.
- **See.** [`db.py`](../backend/app/db.py), [`test_api_photo_validation.py`](../backend/tests/test_api_photo_validation.py).

## 8. Every failure is readable and says what to try

- **Decision.** All errors, including unexpected crashes, come back as
  `{detail, hint, error_id}`. The error handler is installed *before* the CORS middleware, so even a
  crash carries the headers the browser needs. Unexpected crashes get a short reference that also
  appears in the log with the full traceback. The Anthropic key is never included in an error response (covered by a test).
- **Why.** A fresh-install test on 2026-10-13 showed the opposite: pressing "Sync now" with no
  Flickr account crashed the server, the browser could not read the response, and the page blamed the
  backend for being down. The fix is a contract, not a patch per endpoint, so new errors are covered.
- **Cost.** A generic message for true bugs, with the detail in the log. That is the intended
  trade: nothing internal reaches the page.
- **See.** [`errors.py`](../backend/app/errors.py), the troubleshooting table in
  [`QUICKSTART.md`](QUICKSTART.md), [error format](API_DOCUMENTATION.md).

## 9. What was deliberately left out

Stopping was a recorded decision, not an omission:

- **Duplicate-photo detection:** stopped, not shipped, when real data showed the first heuristic
  flagged 499 of 594 photos ([recap 2026-08-05](Read%20Me/README-2026-08-05-1153.md)). The same
  recap found that only 1 of 594 photos carries GPS, so matching relies on capture time, and photo
  clusters use date plus gaps in capture time, not location.
- **Hosting and multi-user:** parked (decision 5).
- **A no-account demo mode:** designed, then dropped on 2026-10-13. It would have added a second
  mode of operation to a project that was ready to close, for people who would mostly read the
  documents. Clear error messages were judged enough for a first run.
- **Frontend automated tests:** none. The front end is type-checked; the 114 automated tests cover
  the backend.
- **Licensing:** the code is source-available and noncommercial ([`LICENSE`](../LICENSE)), so anyone
  can run and learn from it, and commercial use needs permission.

## What I would revisit first

If the project continued: hosting and accounts (which unlocks multi-user), the choice of Postgres
over SQLite that goes with it, and automated tests for the frontend. The open items are on the
issues board.

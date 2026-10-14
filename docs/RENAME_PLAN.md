# Pictala Rename — Project Plan (BirdTrip → Pictala)

> Where this document cites an issue by number, it refers to the project's [issues board](https://github.com/JennSW/Pictala/issues).

Tracks execution of the rename triggered by the naming conflict discovered
2026-09-01 (see [`NAMING_REVIEW.md`](NAMING_REVIEW.md) and issue #61, "Rename of
app"). **The name, Pictala, was decided 2026-09-03.** This plan covers what had to
change, what could stay the same, and what is still open.

**Status as of 2026-10-13:** the rename itself is complete (in-app strings, Flickr app,
GitHub repo and board, portfolio site, artifacts, LinkedIn) and issue #61 was closed on
2026-09-14. A few small leftovers remain; they are listed next.

## Still open (2026-10-13)

Found by re-checking the live site and the code on 2026-10-13.

| # | Item | Where | Who |
|---|---|---|---|
| 1 | **GoDaddy's auto-generated SEO description** on `/pictala-kickoff` still reads "Join the BirdTrip kickoff for an adventure travel experience!" It appears in the page's description, `og:` and `twitter:` meta tags, so it shows in search results and link previews. | GoDaddy page settings | Jen |
| 2 | The **homepage and `/pictala-story` still link to the old slug** `/birdtrip-kickoff`. It works, because the old slug redirects (301) to `/pictala-kickoff`, but the links should point at the new slug. | Embed HTML | Claude drafts, Jen publishes |
| 3 | **Old name in the repo's user-visible text**: `start.sh` (its header and 3 console messages) and `frontend/package.json` (package name). Section 3 below explains why this now matters. | Code | Claude, on request |
| 4 | **Local directory** still named `birdtrip-app 2` (issue #93). Renaming it breaks the virtual environment's script wrappers, which hardcode its path; rebuild it afterward (`rm -rf .venv && python3.12 -m venv .venv && pip install -r requirements.txt`). | Local machine | Jen, when ready |
| 5 | **Older documents still say "BirdTrip"** (a few mentions each in the PRD, design doc, user stories, and others). Proposed: leave them as historical and have the README explain the rename, with no rename pass. | Docs | Jen to confirm |

**Decided 2026-10-13: keep the "Formerly BirdTrip" footnote on `/pictala`.** It is intentional.
The old name is in use by another product, so the footnote records that we know about it and
changed the name as a result, and it also covers any reference to the old name that was missed.
It is the only visible old-name text left on the site.

## Status key

- **Done** — completed and verified.
- **Independent** — should happen on its own timeline, regardless of the app name.
- **Open investigation** — an unresolved question that needs an answer before the task under it can be scoped.
- *Blocked on name decision* and *Deferred* applied before 2026-09-03 and no longer apply.

---

## 1. Must change now, independent of the app rename

The app itself isn't deployed anywhere public, but one surface already is: the public
job-search portfolio site. It carried real exposure and could not wait on the app rename.

| Item | What needed to happen | Status |
|---|---|---|
| theswiftbrain.com pages | Replace "BirdTrip" references with the new name and keep old links working | **Done 2026-09-14**: nav renamed to "Pictala"; the Kickoff page's on-page heading was fixed by Jen (it still showed "BIRDTRIP KICKOFF" although the tab title already said Pictala). **Re-verified 2026-10-13 by live fetch:** all six pages load; `/birdtrip` and `/birdtrip-kickoff` return 301 redirects to `/pictala` and `/pictala-kickoff`; the only visible old-name text is the intentional "Formerly BirdTrip" footnote (kept by decision, see above). The SEO-description and old-slug-link items above remain. |
| Published Claude Artifacts ("BirdTrip Program Toolkit," "BirdTrip Kickoff") | Retitle, or hold off sharing until renamed | **Done 2026-09-14**: all 5 portfolio artifacts checked. Program Toolkit and Kickoff retitled (title and h1). Two more were found during the sweep, The Swift Brain (main portfolio page) and Kickoff Playbook, each with a link card still labeled "BirdTrip Kickoff"; both updated to "Pictala Kickoff". Narrative prose describing historical work (e.g. "BirdTrip's 5 database tables") was left as-is on purpose: it accurately describes what happened before the rename and is not a label. |
| LinkedIn / outreach content referencing BirdTrip by name | Audit and update wording | **Done 2026-09-14**: Jen updated the LinkedIn article (added "formerly BirdTrip" and new screenshots) and the profile post text, and audited the profile page itself, confirming no remaining mentions (recorded on #61). One known limit: the profile post's *image* cannot be edited after publishing (a LinkedIn limitation). |

**Why this was separate:** it was live, public, and tied to active job outreach, the
only genuine trademark-adjacent exposure that existed at the time.

---

## 2. Must change before any public app launch

The user-visible strings inside the app. A contained find-and-replace, not a structural
change. (Line numbers are as of 2026-09-02.)

| Location | What it is | Change needed |
|---|---|---|
| `frontend/index.html:6` | `<title>BirdTrip</title>` | Browser tab title |
| `frontend/src/App.tsx:1163` | `<span className="wordmark">BirdTrip</span>` | In-app logo/wordmark |
| `frontend/src/SyncPanel.tsx:147` | "BirdTrip works best with your eBird data…" | User-facing help copy |
| `backend/app/main.py:11` | `title="BirdTrip API"` | Title shown on the auto-generated `/docs` Swagger page |

Status: **Done** (commit `3bc5ac7`, 2026-09-03). Verified live in the browser tab,
the in-app header, and the Swagger UI title.

---

## 3. Internal code names

These were left as internal code names on 2026-09-03 because the repo was private and
none of it was visible to anyone else. **That reasoning changes if the repo goes public,
because everything in it then becomes visible.** State as of 2026-10-13, by search:

| Location | What it is | Visible to a visitor? | Recommendation |
|---|---|---|---|
| `start.sh` (header and 3 console messages: "BirdTrip is starting up", "Stopping BirdTrip…", and the Ctrl+C reminder) | Local run script | **Yes**, to anyone who runs it or reads it | Rename the text; no functional impact |
| `frontend/package.json` (`"name": "birdtrip-frontend"`) | npm package name | Yes, in the repo | Rename; no functional impact |
| Code comments: `frontend/src/theme.css:1`, `frontend/src/App.tsx:995`, `backend/app/schemas.py:94`, one in `docs/mockups/outing-grouping-mockup.html` | Comments and docstrings | Yes, in the repo, but not in any UI or API docs | Rename opportunistically |
| `backend/app/config.py:27` and `backend/.env.example:23` (`sqlite:///./birdtrip.db`) | Default database filename | Yes, in the repo | Rename **only with care**: changing the default points the app at a new, empty database unless the existing file is renamed too, or `DATABASE_URL` is set explicitly. |
| `frontend/src/App.tsx:123-124` (`birdtrip_last_load`) | localStorage key for the "new since last visit" marker | Only in browser dev tools | Leave, or rename and accept that the marker resets once |
| Older docs (PRD, design doc, user stories, etc.) | Planning documents | Yes, in the repo | Left as historical; see "Still open" item 5 |

Status: **Open for decision** on whether to rename the visible items before the repo is
published. The behavior-affecting items (database filename, localStorage key) need a
deliberate pass rather than a find-and-replace.

---

## 4. External registrations

| Item | Open question | Status |
|---|---|---|
| GitHub repo `JennSW/BirdTrip` | None; renaming is a simple settings change and GitHub redirects the old clone URL | **Done 2026-09-14**: renamed to `JennSW/Pictala`. Confirmed the old URL redirects (`git ls-remote` and `gh api` both resolved), then pointed the local `origin` remote at the new URL. The GitHub Project board was renamed too ("Jen Swift BirdTrip" → "Jen Swift Pictala"), with the same project ID and no items affected. The repo is still private as of 2026-10-13. |
| eBird API key | None; tied to the account, not a public app name | No action needed |
| Flickr API app (registered in Flickr's App Garden) | Was renaming a simple dashboard edit, or did it need new keys? | **Done 2026-09-14**: Jen renamed the app to "Pictala" in the App Garden dashboard; a live `flickr.test.login` call afterward confirmed the existing key, secret, and OAuth token still authenticate. A simple dashboard edit; no re-registration. |
| Domains | Which to register? `pictala.com` is a premium resale listing | **`pictala.app` registered 2026-09-03** (via GoDaddy); on 2026-10-13 it forwards to `theswiftbrain.com/pictala`. `pictala.com` is still a paid BrandBucket listing (not purchased). `pictala.io`: no response on 2026-10-13; whether it is registered was not checked. |
| Local project directory | Rename `birdtrip-app 2` to match | **Open** (issue #93); see "Still open" item 4 |

Posted to issue #61 on 2026-09-02 for tracking:
https://github.com/JennSW/BirdTrip/issues/61#issuecomment-5516888914

---

## 5. Naming decision

**Pictala**, decided 2026-09-03. The full candidate history (151 entries) and the
reasoning are in [`NAMING_REVIEW.md`](NAMING_REVIEW.md).

---

## Summary: did the name decision block anything?

**No.** Sections 2 and 3 never touched data models, business logic, or API design, so
feature work continued freely while the name was undecided. The only time-sensitive item
was Section 1 (the live public portfolio site), and it was independent of the app name.

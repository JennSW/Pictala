# Field test checklist — next trip

Scenarios worth deliberately capturing on the next outing, so real data
exercises app paths that tonight's session (2026-08-07, Juanita Bay Park)
didn't touch. Priority order — if only doing a couple, do #1 and #3, they're
the two most likely to actually change what gets built next.

- [ ] **1. A non-bird photo** — person, gear, landscape shot mixed into the
      Flickr upload. Real gap: `outing_review.py` currently has no way to
      distinguish "still needs Claude" from "Claude looked, it's not a
      bird" — the mockup's "Not a bird" bucket has no backend data yet.
- [ ] **2. A species on the checklist with no Flickr photo at all.**
      Exercises "No photos on Flickr," built tonight but never populated
      with real data.
- [ ] **3. A Flickr-only guess, not on that day's checklist.** Tonight's
      "To review" list was 100% eBird-matched (icon on every card) — never
      saw the no-icon guess-only case render live.
- [ ] **4. Export the full "Download My Data" CSV** instead of a
      per-checklist download (even for the same day). Today's per-checklist
      export had no scientific names at all, so the eBird-match icon's
      "next to scientific name" layout was never actually tested with real
      text next to it, just the icon-alone fallback.
- [ ] **5. A duplicate photo upload.** Existing `possible_duplicate`
      warning UI never fired tonight since today's data was clean.
- [ ] **6. A photo with a wrong camera clock/timezone.** Existing
      `timezone_mismatch` warning UI, same as above — never fired tonight.
- [ ] **7. Multiple species with several photos each.** The real
      "same-species grouping" question from earlier — real repeats will
      show whether it's still worth building.

See [docs/DESIGN.md](DESIGN.md) for the resolved design decisions these
check against, and [docs/mockups/](mockups/) for the reference layouts.

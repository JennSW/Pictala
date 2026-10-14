# Competitive Landscape

> Where this document cites an issue by number, it refers to the project's [issues board](https://github.com/JennSW/Pictala/issues).

Web-search-based scan (2026-09-02) of apps/tools related to what this
project does — matching an eBird checklist to Flickr photos from the
same outing, with an AI-assisted species-ID review workflow. Same
caveat as `NAMING_REVIEW.md`: these are search-based findings, not
exhaustive market research or a formal competitive audit.

**Trigger:** requested for project positioning and to inform upcoming
feature design, prompted partly by new bird-photography apps the user
had been seeing surfaced on social media.

## Question 1: Does anything do exactly what this app does?

**No exact match found.** Nobody reconciles two *separate systems of
record* — an eBird checklist and an external photo host (Flickr) — for
the same outing, with a review/approve workflow. That specific
data-matching problem (two APIs, no shared key) appears to be a genuine,
unclaimed gap.

Closest attempts, and why they don't overlap directly:

| Tool | What it does | Why it's not the same problem |
|---|---|---|
| [BirdSync](https://github.com/Sajmani/birdsync) | Syncs eBird observations to iNaturalist (one direction only), pulling photos already attached via the Macaulay Library | No Flickr, no "outing" grouping, no review UI — a CLI tool, not an app |
| [Merlin Bird ID](https://merlin.allaboutbirds.org) | eBird's own companion app — photo/audio species ID, "find birds near you" | An identification tool, not a reconciliation tool between two existing libraries |

## Question 2: What's doing something similar?

| App | What it does | How it differs |
|---|---|---|
| **[Perch](https://projectkestrel.org/perch)** (built on Project Kestrel) | Upload a whole outing's local photos → AI groups bursts, scores sharpness, tags species, shares the outing as an interactive timeline/story. Live and launched. Has a "Groups" feature merging multiple people's photos from the same outing into one shared timeline. | Works from local photos only — no eBird checklist import, no cross-referencing against a second system of record. Focused on photo *quality/culling* and *storytelling*, not data reconciliation. |
| **[Project Kestrel](https://projectkestrel.org/)** (Perch's parent app) | Free, open-source, local-only bird-photo culling tool — groups burst shots into scenes, scores sharpness, tags species/family, exports ratings to Lightroom/Capture One | Desktop culling/organization tool, no checklist or outing-review workflow, no cloud/account |
| **[MyBird](https://mybird.life)** | Personal birding journal — photos filed by species (not by outing), GPS pulled from photo EXIF, offline-first, iOS only (Android planned) | Organized by species, not by outing; no eBird or Flickr integration at all |
| **[Birda](https://birda.org)** | Social birding app — own AI photo ID, "Lifer" + "Photographed" lists, community ID help, global sighting map, iOS + Android | No eBird/Flickr integration; standalone social/gamified logging app, not a reconciler |
| **Plumage** (announced on BirdForum, 2026) | Calm, no-algorithm photo-sharing app building a personal field guide/life list from bird photos; auto-obscures sensitive-species locations | Photo-social app, not data-matching; no eBird tie-in mentioned |

## Positioning implications

- The core reconciliation problem (checklist ↔ separate photo host, per
  outing, with a review workflow) still looks genuinely unclaimed —
  worth keeping as the sharp point of the pitch, both for the product
  and the portfolio/interview narrative.
- **Perch's "Groups" feature is real-world validation of the V2
  multi-user/sharing vision** (backlog #16/#17) — a live competitor
  already shipped a version of "merge multiple people's photos from the
  same outing into one shared view," which suggests that's a real,
  wanted feature category, not just a nice-to-have vision item.
- Project Kestrel's burst-grouping/sharpness-scoring/culling is a
  different value-add (photo *quality*) this app doesn't do and
  probably shouldn't chase — it would blur the core differentiator
  (checklist-photo reconciliation) rather than sharpen it.

## Naming cross-reference

**Perch is a live, closely-positioned competitor literally named
"Perch."** This directly affects the in-progress app-renaming work — see
`docs/NAMING_REVIEW.md` and the naming-conflict memory for the full
thread. Flagged there as a risk on the current front-runner name
(**Perchoto**, built on a "Perch-" root) that should be weighed before
finalizing, not discovered after.

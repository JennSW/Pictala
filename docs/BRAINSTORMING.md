# BirdTrip — Brainstorming

Running notes and ideas for the project. Not a roadmap or a commitment —
just a place to capture things as they come up, to revisit later.

## User Stories

To identify species in my photos:

Query Flickr by date, location, keywords
Query Claude for image matching. Use keywords and photo titles as hint in search if available. 
Query eBird for list of species identified in the Flickr + Claude image search.
  Include
    "speciesCode": "",
    "comName": "",
    "sciName": "",

UX
For results page:
  Display location
  Display date
  Flag non-birds
  Flag birds that cannot be identified. 
  
  Allow resulting identification to be edited then approved.
  Provide “Edit” button so the match can be edited. This is not a required action.
  Provide “Save” button for results to be saved as the final list. This is a required action.
  Add a notes field for that day, 3 lines, up to 500 characters. Show character countdown next to field. Provide spell check. This is not a required field.

  If user clicks “Edit” button
  Provide option to approve, remove or park search result by photo.
  Provide option for multi-select to take an action: Approve, Remove, Park
  

-

## Parked / maybe later

-

## V2

- **Additional photo hosting sites** (beyond Flickr) — e.g. SmugMug.
  Needs investigation: which sites are most widely used, and which of
  those support an API BirdTrip could integrate with.
- **Merlin recordings** — investigate whether someone's audio recordings
  saved to Merlin (Cornell's bird ID app) could be brought into BirdTrip.
- **Multi-user support** — let users add their own Flickr user ID and
  Merlin user ID, so the app can be extended to other users beyond just
  me.

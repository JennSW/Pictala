"""Thin Flickr REST client using OAuth 1.0a.

Flickr's auth model is fundamentally different from eBird's: eBird is a
single API key in a header; Flickr requires a one-time 3-legged OAuth 1.0a
handshake to act as your own account (see flickr_oauth_setup.py), after
which the resulting token+secret authenticate every call. That contrast is
worth calling out explicitly in a demo -- "not every API key looks the
same."
"""
import requests
from requests_oauthlib import OAuth1

from app.config import settings

FLICKR_REST_ENDPOINT = "https://api.flickr.com/services/rest/"

PER_PAGE = 500  # Flickr's maximum
MAX_PAGES = 20  # 20 x 500 = 10,000 photos in one range; more than that is a mistake to surface


def _oauth() -> OAuth1:
    return OAuth1(
        client_key=settings.flickr_api_key,
        client_secret=settings.flickr_api_secret,
        resource_owner_key=settings.flickr_oauth_token,
        resource_owner_secret=settings.flickr_oauth_token_secret,
    )


def _expand_bare_date(date_str: str, end_of_day: bool) -> str:
    """Flickr parses a bare "YYYY-MM-DD" min/max_taken_date as midnight for
    *both* bounds -- so min_taken_date == max_taken_date == "2026-08-07"
    (e.g. syncing "today") silently returns zero results, a zero-width
    range, even when photos taken that day exist. Expand a bare date to an
    explicit full-day boundary; leave anything that already has a time
    component alone."""
    if len(date_str) == 10:  # "YYYY-MM-DD", no time component
        return f"{date_str} 23:59:59" if end_of_day else f"{date_str} 00:00:00"
    return date_str


def get_photos_in_range(min_taken_date: str, max_taken_date: str) -> list[dict]:
    """Fetch photos for the configured user taken in [min_taken_date,
    max_taken_date] (ISO date strings). Requests all the `extras` we need in
    one call per page so we don't do a second round-trip per photo.

    Follows every page of results. Flickr returns at most PER_PAGE photos per
    request; this function used to read only the first page, so a date range
    holding more than that silently lost the rest (code review 2026-10-13, H2).
    If a range spans more than MAX_PAGES pages it raises instead of returning a
    partial list: a loud, fixable error ("narrow the date range") is better
    than a sync that looks successful and is incomplete.
    """
    base_params = {
        "method": "flickr.people.getPhotos",
        "user_id": settings.flickr_user_id,
        "min_taken_date": _expand_bare_date(min_taken_date, end_of_day=False),
        "max_taken_date": _expand_bare_date(max_taken_date, end_of_day=True),
        "extras": "date_taken,geo,tags,url_m",
        "format": "json",
        "nojsoncallback": 1,
        "per_page": PER_PAGE,
    }
    photos: list[dict] = []
    seen_ids: set[str] = set()
    page = 1
    while True:
        resp = requests.get(
            FLICKR_REST_ENDPOINT, params={**base_params, "page": page}, auth=_oauth(), timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("stat") != "ok":
            raise RuntimeError(f"Flickr API error: {data}")

        block = data["photos"]
        for photo in block.get("photo", []):
            # Photos uploaded between two page requests can shift the ordering,
            # so the same photo can appear on two pages. The caller inserts
            # without flushing, so a repeated id would violate the unique
            # flickr_id constraint -- keep each photo once.
            if photo["id"] not in seen_ids:
                seen_ids.add(photo["id"])
                photos.append(photo)

        total_pages = int(block.get("pages") or 1)  # Flickr sends 0 for "no results"
        if page >= total_pages:
            return photos
        if page >= MAX_PAGES:
            raise RuntimeError(
                f"This date range has {total_pages} pages of photos "
                f"({total_pages * PER_PAGE} at most), more than the {MAX_PAGES}-page "
                f"limit. Narrow the date range and sync again."
            )
        page += 1

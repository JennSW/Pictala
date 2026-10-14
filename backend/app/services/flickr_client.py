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
from app.errors import BadInputError, ExternalServiceError, NotConfiguredError

FLICKR_REST_ENDPOINT = "https://api.flickr.com/services/rest/"

PER_PAGE = 500  # Flickr's maximum
MAX_PAGES = 20  # 20 x 500 = 10,000 photos in one range; more than that is a mistake to surface


_FLICKR_SETTINGS = {
    "FLICKR_API_KEY": "flickr_api_key",
    "FLICKR_API_SECRET": "flickr_api_secret",
    "FLICKR_OAUTH_TOKEN": "flickr_oauth_token",
    "FLICKR_OAUTH_TOKEN_SECRET": "flickr_oauth_token_secret",
    "FLICKR_USER_ID": "flickr_user_id",
}


def require_flickr_configured() -> None:
    """Fail early, and helpfully, if Flickr hasn't been set up. Without this the first
    "Sync now" sent an empty key to Flickr and surfaced Flickr's "Invalid API Key"."""
    missing = [name for name, attr in _FLICKR_SETTINGS.items() if not getattr(settings, attr)]
    if missing:
        raise NotConfiguredError(
            "Flickr isn't connected yet, so there are no photos to pull in.",
            "To use your own photos, add your Flickr details to backend/.env "
            f"(still missing: {', '.join(missing)}), run `python -m app.services.flickr_oauth_setup` "
            "from the backend folder once, then restart. The steps are under 'Get your credentials' "
            "in docs/QUICKSTART.md. Without Flickr you can still upload an eBird CSV to browse your outings and species.",
        )


def raise_for_flickr_error(data: dict) -> None:
    """Turn a Flickr `stat: fail` reply into a message that says what to fix.
    Codes are the ones Flickr documents for its REST API."""
    if data.get("stat") == "ok":
        return
    code = data.get("code")
    flickr_says = data.get("message", "no message")
    if code == 100:
        raise ExternalServiceError(
            "Flickr rejected your API key.",
            "Check FLICKR_API_KEY and FLICKR_API_SECRET in backend/.env against the app you created at "
            "https://www.flickr.com/services/apps/, then restart the backend.",
        )
    if code in (96, 97, 98, 99):
        raise ExternalServiceError(
            "Flickr didn't accept your authorization. It may have expired, been revoked, or been "
            "copied incorrectly.",
            "Run `python -m app.services.flickr_oauth_setup` from the backend folder again, paste the "
            "new token and secret into backend/.env, then restart the backend.",
        )
    if code == 1:
        raise ExternalServiceError(
            "Flickr couldn't find that user.",
            "Check FLICKR_USER_ID in backend/.env. It looks like 12345678@N00 and appears in the "
            "output of the setup script.",
        )
    if code in (105, 106):
        raise ExternalServiceError(
            "Flickr is temporarily unavailable.", "Try again in a few minutes."
        )
    raise ExternalServiceError(
        f"Flickr reported an error: {flickr_says} (code {code}).",
        "If this keeps happening, check the Flickr details in backend/.env and Flickr's own status page.",
    )


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
    require_flickr_configured()
    photos: list[dict] = []
    seen_ids: set[str] = set()
    page = 1
    while True:
        resp = requests.get(
            FLICKR_REST_ENDPOINT, params={**base_params, "page": page}, auth=_oauth(), timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        raise_for_flickr_error(data)

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
            raise BadInputError(
                f"That date range has {total_pages * PER_PAGE} photos at most "
                f"({total_pages} pages), more than one sync can fetch ({MAX_PAGES} pages).",
                "Narrow the date range and sync again, for example one year at a time.",
            )
        page += 1

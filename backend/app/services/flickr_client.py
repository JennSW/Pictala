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


def _oauth() -> OAuth1:
    return OAuth1(
        client_key=settings.flickr_api_key,
        client_secret=settings.flickr_api_secret,
        resource_owner_key=settings.flickr_oauth_token,
        resource_owner_secret=settings.flickr_oauth_token_secret,
    )


def get_photos_in_range(min_taken_date: str, max_taken_date: str) -> list[dict]:
    """Fetch photos for the configured user taken in [min_taken_date,
    max_taken_date] (ISO date strings). Requests all the `extras` we need in
    one call so we don't do a second round-trip per photo.
    """
    params = {
        "method": "flickr.people.getPhotos",
        "user_id": settings.flickr_user_id,
        "min_taken_date": min_taken_date,
        "max_taken_date": max_taken_date,
        "extras": "date_taken,geo,tags,url_m",
        "format": "json",
        "nojsoncallback": 1,
        "per_page": 500,
    }
    resp = requests.get(FLICKR_REST_ENDPOINT, params=params, auth=_oauth(), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("stat") != "ok":
        raise RuntimeError(f"Flickr API error: {data}")
    return data["photos"]["photo"]

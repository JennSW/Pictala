"""Per-photo EXIF lookup -- separate from flickr_client.get_photos_in_range
because `flickr.photos.getExif` is a second API call per photo (not part
of the `extras` on flickr.people.getPhotos), so callers should only reach
for this when they actually need EXIF fields, not on every sync.

Built for the timezone-mismatch check (issue #6): the camera's
`OffsetTimeOriginal` tag records what UTC offset the camera *thought* it
was in when the photo was taken -- if that's wrong (clock never updated
while traveling), this is the only way to catch it, since Flickr's
`date_taken` is just the camera's wall-clock time with no offset attached.
"""
import requests

from app.services.flickr_client import _oauth, FLICKR_REST_ENDPOINT


def get_utc_offset(flickr_id: str) -> str | None:
    """Returns the camera-recorded UTC offset (e.g. "-08:00") for a
    photo, or None if the call fails or no camera wrote the tag. Prefers
    `OffsetTimeOriginal` (when the shutter was pressed) over `OffsetTime`
    (when the file was last modified) since the two can legitimately
    differ (e.g. edited later, in a different timezone, in Lightroom)."""
    params = {
        "method": "flickr.photos.getExif",
        "photo_id": flickr_id,
        "format": "json",
        "nojsoncallback": 1,
    }
    resp = requests.get(FLICKR_REST_ENDPOINT, params=params, auth=_oauth(), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("stat") != "ok":
        return None

    tags = {tag["tag"]: tag["raw"]["_content"] for tag in data.get("photo", {}).get("exif", [])}
    return tags.get("OffsetTimeOriginal") or tags.get("OffsetTime")

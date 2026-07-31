"""eBird taxonomy lookup -- resolves a common name (e.g. from an AI
species guess) to eBird's standard metadata (speciesCode, comName,
sciName). See docs/USER_STORIES.md, "Species ID fallback for eBird
gaps".

The taxonomy is large (~18k species) but effectively stable -- eBird
updates it roughly once a year -- so it's fetched once and cached
in-process rather than re-fetched on every lookup.
"""
import requests

from app.config import settings

_TAXONOMY_CACHE: list[dict] | None = None


def _load_taxonomy() -> list[dict]:
    global _TAXONOMY_CACHE
    if _TAXONOMY_CACHE is None:
        resp = requests.get(
            "https://api.ebird.org/v2/ref/taxonomy/ebird",
            params={"fmt": "json"},
            headers={"x-ebirdapitoken": settings.ebird_api_key},
            timeout=30,
        )
        resp.raise_for_status()
        _TAXONOMY_CACHE = resp.json()
    return _TAXONOMY_CACHE


def find_species(common_name: str) -> dict | None:
    """Case-insensitive exact match against eBird's common name. Returns
    {species_code, common_name, scientific_name}, or None if this isn't
    a name eBird's taxonomy recognizes at all -- e.g. the model named
    something outside real bird taxonomy entirely, which should be
    treated as "couldn't identify," not silently accepted."""
    target = common_name.strip().lower()
    for entry in _load_taxonomy():
        if entry.get("comName", "").lower() == target:
            return {
                "species_code": entry["speciesCode"],
                "common_name": entry["comName"],
                "scientific_name": entry["sciName"],
            }
    return None

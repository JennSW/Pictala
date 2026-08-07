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


def resolve_guess(common_name: str | None) -> tuple[str | None, str | None, str | None, bool]:
    """Resolve a raw guessed name (from an AI suggestion or a hand-typed
    note) against eBird's taxonomy. Returns (common_name,
    scientific_name, species_code, is_other). Shared by every fallback-ID
    endpoint -- checklist-scoped (match.py) and checklist-less
    (unassigned.py) alike -- since resolving a guess against the
    taxonomy doesn't care which flow it came from."""
    if not common_name:
        return None, None, None, False
    resolved = find_species(common_name)
    if resolved:
        return resolved["common_name"], resolved["scientific_name"], resolved["species_code"], False
    # Not in eBird's bird taxonomy -- either genuinely not a bird (a
    # dragonfly, a squirrel) or a bird named in a way the taxonomy
    # doesn't recognize. Either way this is a legitimate "Other" guess to
    # offer, not an error to discard -- the model still gets to propose
    # *something*, per the non-bird case discovered live
    # (docs/USER_STORIES.md, "Species ID fallback for eBird gaps").
    return common_name, None, None, True

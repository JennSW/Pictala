"""Unit tests for resolve_guess -- shared by match.py and unassigned.py's
fallback-ID endpoints (previously copy-pasted in both as
_resolve_fallback_guess / _resolve_guess before consolidating here).

find_species() hits eBird's live taxonomy API on first call (cached
in-process after that -- see ebird_taxonomy.py's module docstring), so
these tests monkeypatch it directly rather than exercising the real
network call: resolve_guess's own branching logic is what's under test,
not eBird's taxonomy contents.
"""
from app.services import ebird_taxonomy


def test_resolves_known_species(monkeypatch):
    monkeypatch.setattr(
        ebird_taxonomy,
        "find_species",
        lambda name: {
            "common_name": "Great Blue Heron",
            "scientific_name": "Ardea herodias",
            "species_code": "grbher3",
        },
    )
    common_name, scientific_name, species_code, is_other = ebird_taxonomy.resolve_guess(
        "great blue heron"
    )
    assert common_name == "Great Blue Heron"
    assert scientific_name == "Ardea herodias"
    assert species_code == "grbher3"
    assert is_other is False


def test_unrecognized_name_is_a_legitimate_other_guess(monkeypatch):
    """Not in eBird's taxonomy at all (e.g. "Dragonfly") -- treated as a
    legitimate "Other" guess to offer, not an error, per the non-bird
    case discovered live (docs/USER_STORIES.md, "Species ID fallback for
    eBird gaps")."""
    monkeypatch.setattr(ebird_taxonomy, "find_species", lambda name: None)
    common_name, scientific_name, species_code, is_other = ebird_taxonomy.resolve_guess("Dragonfly")
    assert common_name == "Dragonfly"
    assert scientific_name is None
    assert species_code is None
    assert is_other is True


def test_none_input_resolves_to_all_none():
    common_name, scientific_name, species_code, is_other = ebird_taxonomy.resolve_guess(None)
    assert (common_name, scientific_name, species_code, is_other) == (None, None, None, False)


def test_empty_string_input_resolves_to_all_none():
    common_name, scientific_name, species_code, is_other = ebird_taxonomy.resolve_guess("")
    assert (common_name, scientific_name, species_code, is_other) == (None, None, None, False)

"""Unit tests for the duplicate-detection heuristic (issue #39). The
matching rule itself is documented (and was verified against live data)
in app/services/duplicate_detection.py's module docstring -- these tests
encode that same reasoning as regression cases, particularly the v1/v2/v3
history: a naive approach over-flags real sequential photos, and the
cases below are exactly the ones that told us so.

Pure-function tests -- no DB session needed, since compute_duplicate_group_keys
takes plain Photo objects and returns a dict, no I/O.
"""
from app.models import Photo
from app.services.duplicate_detection import compute_duplicate_group_keys


def _photo(id: int, title: str | None, date_taken: str) -> Photo:
    return Photo(id=id, title=title, date_taken=date_taken)


def test_real_duplicate_pair_is_flagged():
    """The actual case that motivated #39: a re-exported copy with a
    real camera frame number suffix."""
    photos = [
        _photo(1, "July 11-02239", "2026-07-11T10:00:00"),
        _photo(2, "July 11-02239-2", "2026-07-11T10:05:00"),
    ]
    keys = compute_duplicate_group_keys(photos)
    assert keys[1] == keys[2]
    assert keys[1] is not None


def test_copy_suffix_pair_is_flagged():
    photos = [
        _photo(1, "July 11-02022", "2026-07-11T10:00:00"),
        _photo(2, "July 11-02022 copy", "2026-07-11T10:05:00"),
    ]
    keys = compute_duplicate_group_keys(photos)
    assert keys[1] == keys[2]


def test_sequential_day_numbering_is_not_flagged():
    """v1's false-positive case: this account's own naming convention is
    sequential dash-numbers within a day ("June 7-1" .. "June 7-26") --
    genuinely different photos, not duplicates, even though the shape
    looks identical to the real signature. The distinguishing factor is
    frame-number length (short day-counter vs. long camera frame number),
    not the dash itself."""
    photos = [
        _photo(1, "June 7-1", "2026-06-07T09:00:00"),
        _photo(2, "June 7-2", "2026-06-07T09:01:00"),
        _photo(3, "June 7-26", "2026-06-07T09:30:00"),
    ]
    keys = compute_duplicate_group_keys(photos)
    assert keys == {}


def test_unsuffixed_first_photo_of_day_is_not_flagged():
    """v2's false-positive case: some days number sequentially starting
    unsuffixed ("June 8", "June 8-2", "June 8-3"...), so the bare base
    legitimately exists as photo #1 of the day, not a duplicate's
    original."""
    photos = [
        _photo(1, "June 8", "2026-06-08T09:00:00"),
        _photo(2, "June 8-2", "2026-06-08T09:01:00"),
        _photo(3, "June 8-3", "2026-06-08T09:02:00"),
    ]
    keys = compute_duplicate_group_keys(photos)
    assert keys == {}


def test_suffixed_photo_with_no_matching_base_is_not_flagged():
    """A frame-number-length suffix alone isn't enough -- the base title
    also has to exist as its own real photo on the same day."""
    photos = [_photo(1, "July 11-02239-2", "2026-07-11T10:05:00")]
    keys = compute_duplicate_group_keys(photos)
    assert keys == {}


def test_same_title_different_day_is_not_grouped():
    """Same calendar day is part of the match, not just the exact
    title -- a title collision across different days shouldn't group."""
    photos = [
        _photo(1, "July 11-02239", "2026-07-11T10:00:00"),
        _photo(2, "July 11-02239-2", "2026-07-12T10:05:00"),
    ]
    keys = compute_duplicate_group_keys(photos)
    assert keys == {}


def test_photo_with_no_title_is_skipped():
    photos = [
        _photo(1, None, "2026-07-11T10:00:00"),
        _photo(2, "July 11-02239-2", "2026-07-11T10:05:00"),
    ]
    keys = compute_duplicate_group_keys(photos)
    assert keys == {}


def test_group_of_three_share_one_key():
    """Two suffixed copies of the same base all land in one group, not
    three pairwise groups."""
    photos = [
        _photo(1, "July 11-02239", "2026-07-11T10:00:00"),
        _photo(2, "July 11-02239-2", "2026-07-11T10:05:00"),
        _photo(3, "July 11-02239-3", "2026-07-11T10:06:00"),
    ]
    keys = compute_duplicate_group_keys(photos)
    assert keys[1] == keys[2] == keys[3]

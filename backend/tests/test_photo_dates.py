"""Tests for title-date fallback (issue #34): when Flickr's date_taken is
just an upload-time fallback, the date in the photo's title is the real
capture day.

The title shapes below are real ones from this library, not invented.
"""
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Checklist, Match, Photo
from app.services.matcher import run_rule_based_matching
from app.services.photo_clusters import compute_clusters
from app.services.photo_dates import effective_day, parse_title_date

TAKEN = datetime(2026, 10, 8, 17, 28, 32)  # Flickr's upload-time fallback


@pytest.mark.parametrize(
    "title, expected",
    [
        ("October 7 2026", date(2026, 10, 7)),
        ("Oct 7-04008", date(2026, 10, 7)),  # no year -> taken's year
        ("October 8 - IH", date(2026, 10, 8)),
        ("Sept 17 2026 - Juanita Bay Park", date(2026, 9, 17)),
        ("July 23 Issaquah Highlands", date(2026, 7, 23)),
        ("June 7-26", date(2026, 6, 7)),  # trailing number is a photo counter, not a year
    ],
)
def test_real_title_shapes_parse(title, expected):
    assert parse_title_date(title, TAKEN) == expected


@pytest.mark.parametrize(
    "title",
    [None, "", "IMG_4082", "May 2026 trip", "Marymoor Park August 1", "Marsh wren 3", "Feb 30 2026"],
)
def test_titles_without_a_leading_date_are_ignored(title):
    assert parse_title_date(title, TAKEN) is None


def test_missing_year_rolls_back_when_title_would_be_in_the_future():
    """A Dec 30 title on a photo Flickr dated Jan 2 means last December."""
    assert parse_title_date("Dec 30", datetime(2027, 1, 2, 9, 0)) == date(2026, 12, 30)


def _photo(title, taken="2026-10-08T17:28:32", id=1):
    return Photo(id=id, flickr_id=f"f{id}", title=title, date_taken=taken)


def test_title_day_earlier_than_flickr_date_wins():
    day, from_title = effective_day(_photo("October 7 2026"))
    assert (day, from_title) == (date(2026, 10, 7), True)


def test_title_matching_flickr_date_is_not_flagged():
    day, from_title = effective_day(_photo("October 8 - IH"))
    assert (day, from_title) == (date(2026, 10, 8), False)


def test_title_day_later_than_flickr_date_is_ignored():
    """An upload-time fallback can only be later than the real date, never
    earlier -- so a later title date is a typo, not a correction."""
    day, from_title = effective_day(_photo("October 9 2026"))
    assert (day, from_title) == (date(2026, 10, 8), False)


def test_unparseable_flickr_date_gives_no_day():
    assert effective_day(_photo("October 7 2026", taken="")) == (None, False)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _checklist(db, date_iso="2026-10-07", start="07:36 AM", minutes=168):
    c = Checklist(
        submission_id="S1", location_name="Juanita Bay Park", date=date_iso,
        start_time=start, duration_minutes=minutes,
    )
    db.add(c)
    db.flush()
    return c


def test_titled_photo_uploaded_next_day_matches_by_same_day(db_session):
    """The #34 case itself: photos shot Oct 7, uploaded Oct 8 with no EXIF
    date. Without the title fallback they were never even considered."""
    _checklist(db_session)
    db_session.add(_photo("October 7 2026"))
    db_session.commit()

    run_rule_based_matching(db_session)

    match = db_session.query(Match).one()
    assert match.method == "rule_based_same_day"


def test_title_date_never_produces_a_tight_time_window_match(db_session):
    """A title gives a day, not a time. Upload time-of-day 08:30 happens to
    fall inside the 07:36 checklist window -- that is coincidence, and must
    not be reported as a precise rule_based match."""
    _checklist(db_session)
    db_session.add(_photo("October 7 2026", taken="2026-10-08T08:30:00"))
    db_session.commit()

    run_rule_based_matching(db_session)

    assert db_session.query(Match).one().method == "rule_based_same_day"


def test_photo_with_a_correct_date_still_matches_tightly(db_session):
    _checklist(db_session)
    db_session.add(_photo("October 7 2026", taken="2026-10-07T08:30:00"))
    db_session.commit()

    run_rule_based_matching(db_session)

    assert db_session.query(Match).one().method == "rule_based"


def test_photo_titled_for_a_different_day_does_not_match(db_session):
    """The 11 'October 8 - IH' photos: Oct 8 is their real day, so an Oct 7
    checklist must not claim them."""
    _checklist(db_session)
    db_session.add(_photo("October 8 - IH"))
    db_session.commit()

    run_rule_based_matching(db_session)

    assert db_session.query(Match).count() == 0


def test_photo_only_clusters_use_the_titled_day(db_session):
    db_session.add(_photo("October 7 2026", id=1))
    db_session.add(_photo("October 8 - IH", id=2, taken="2026-10-08T17:50:00"))
    db_session.commit()

    days = sorted(c["date"] for c in compute_clusters(db_session))

    assert days == ["2026-10-07", "2026-10-08"]

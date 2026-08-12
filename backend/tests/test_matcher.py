"""Unit tests for the deterministic matcher -- the point of Strategy A is
that it's cheap to test exhaustively, so do that.

Run with: pytest (from backend/), using an in-memory SQLite DB.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Checklist, Match, Observation, Photo
from app.services.matcher import run_rule_based_matching


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_photo_inside_window_matches(db_session):
    checklist = Checklist(
        submission_id="S1",
        location_name="Lake Merritt",
        latitude=37.8078,
        longitude=-122.2497,
        date="2026-06-14",
        start_time="07:30",
        duration_minutes=60,
    )
    db_session.add(checklist)
    db_session.flush()
    db_session.add(
        Observation(checklist_id=checklist.id, common_name="Snowy Egret", scientific_name="Egretta thula")
    )
    db_session.add(
        Photo(
            flickr_id="p1",
            title="Snowy Egret fishing",
            date_taken="2026-06-14T07:50:00",
            latitude=37.8079,
            longitude=-122.2498,
        )
    )
    db_session.commit()

    result = run_rule_based_matching(db_session)

    assert result["checklist_photo_matches"] == 1
    assert result["species_level_matches"] == 1


def test_species_text_match_handles_space_stripped_flickr_tags(db_session):
    """Real Flickr tags conventionally strip spaces from multi-word terms
    (e.g. "tuftedpuffin", not "tufted puffin") -- a literal substring
    check against the common name alone would miss this."""
    checklist = Checklist(
        submission_id="S1",
        location_name="Smith Island",
        latitude=48.3199,
        longitude=-122.8417,
        date="2026-06-14",
        start_time="07:30",
        duration_minutes=60,
    )
    db_session.add(checklist)
    db_session.flush()
    db_session.add(
        Observation(checklist_id=checklist.id, common_name="Tufted Puffin", scientific_name="Fratercula cirrhata")
    )
    db_session.add(
        Photo(
            flickr_id="p1",
            title="Salish Sea trip",
            tags="kenmorecamera salish sea tuftedpuffin smithisland",
            date_taken="2026-06-14T07:50:00",
            latitude=48.3199,
            longitude=-122.8417,
        )
    )
    db_session.commit()

    result = run_rule_based_matching(db_session)

    assert result["checklist_photo_matches"] == 1
    assert result["species_level_matches"] == 1


def test_photo_outside_window_does_not_match(db_session):
    checklist = Checklist(
        submission_id="S1",
        location_name="Lake Merritt",
        date="2026-06-14",
        start_time="07:30",
        duration_minutes=60,
    )
    db_session.add(checklist)
    db_session.flush()
    db_session.add(
        Photo(flickr_id="p1", title="Random bird", date_taken="2026-06-15T07:50:00")
    )
    db_session.commit()

    result = run_rule_based_matching(db_session)

    assert result["checklist_photo_matches"] == 0


def test_same_day_fallback_still_runs_when_checklist_already_has_tight_matches(db_session):
    """Regression test for issue #59, found live: a checklist with strong
    tight-window matches used to skip the same-day fallback entirely (it
    only ran when the tight window found zero candidates for the whole
    checklist), so an outlier same-day photo -- e.g. one with a wrong
    camera clock/timezone offset landing its recorded time hours outside
    the window -- got no match at all instead of falling back. Real case:
    an outing with 17 photos correctly inside the tight window, plus 2
    more genuinely-same-day photos recorded ~6 hours later than reality
    due to a wrong EXIF timezone offset."""
    checklist = Checklist(
        submission_id="S1",
        location_name="Lake Merritt",
        date="2026-06-14",
        start_time="13:33",
        duration_minutes=216,
    )
    db_session.add(checklist)
    db_session.flush()
    db_session.add(
        Photo(flickr_id="p1", title="In the tight window", date_taken="2026-06-14T14:06:47")
    )
    db_session.add(
        Photo(
            flickr_id="p2",
            title="Same day, clock way off",
            date_taken="2026-06-14T23:07:16",  # same calendar day, well outside the window
        )
    )
    db_session.commit()

    result = run_rule_based_matching(db_session)

    assert result["checklist_photo_matches"] == 2
    assert result["same_day_fallback_matches"] == 1

    methods = {m.photo.flickr_id: m.method for m in db_session.query(Match).all()}
    assert methods["p1"] == "rule_based"
    assert methods["p2"] == "rule_based_same_day"


def test_photo_far_away_does_not_match_even_in_time_window(db_session):
    checklist = Checklist(
        submission_id="S1",
        location_name="Lake Merritt",
        latitude=37.8078,
        longitude=-122.2497,
        date="2026-06-14",
        start_time="07:30",
        duration_minutes=60,
    )
    db_session.add(checklist)
    db_session.flush()
    db_session.add(
        Photo(
            flickr_id="p1",
            title="Bird somewhere else",
            date_taken="2026-06-14T07:50:00",
            latitude=34.0522,  # Los Angeles -- clearly a different outing
            longitude=-118.2437,
        )
    )
    db_session.commit()

    result = run_rule_based_matching(db_session)

    assert result["checklist_photo_matches"] == 0

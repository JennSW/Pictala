"""Regression tests for the eBird CSV importer's re-import behavior (issue
#95).

eBird's "Download My Data" export is cumulative -- every upload contains
your whole history -- so re-importing checklists that already exist is the
normal case, not an edge case. These tests pin down what must survive that:
a person's confirmed species links, and nothing duplicated.

Run with: pytest (from backend/), using an in-memory SQLite DB.
"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Checklist, Match, Observation, Photo
from app.services.ebird_import import import_ebird_csv

HEADER = (
    "Submission ID,Common Name,Scientific Name,Count,Location,Location ID,"
    "Latitude,Longitude,Date,Time,Duration (Min)\n"
)


def _row(sid, common, sci, count="1", date="14 Jun 2026"):
    return f"{sid},{common},{sci},{count},Lake Merritt,L1,37.8,-122.2,{date},07:30,60\n"


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _write_csv(tmp_path, name, rows):
    path = tmp_path / name
    path.write_text(HEADER + "".join(rows), encoding="utf-8")
    return str(path)


def _confirmed_match(db, checklist, observation, note=None):
    photo = Photo(flickr_id=f"f{observation.id}", date_taken="2026-06-14T07:45:00")
    db.add(photo)
    db.flush()
    match = Match(
        checklist_id=checklist.id,
        photo_id=photo.id,
        observation_id=observation.id,
        method="manual",
        reviewed_at=datetime(2026, 6, 15, 9, 0),
        note=note,
    )
    db.add(match)
    db.commit()
    return match


def _observation_named(db, checklist, common_name):
    return (
        db.query(Observation)
        .filter(Observation.checklist_id == checklist.id, Observation.common_name == common_name)
        .one()
    )


def test_reimport_keeps_confirmed_species_link(db_session, tmp_path):
    """The #95 bug itself: the importer deletes and recreates a checklist's
    Observation rows, so a confirmed match must be re-pointed at the
    recreated row for the same species -- not left as 'Unmatched'."""
    csv_path = _write_csv(tmp_path, "history.csv", [
        _row("S1", "Snowy Egret", "Egretta thula"),
        _row("S1", "Mallard", "Anas platyrhynchos"),
    ])
    import_ebird_csv(db_session, csv_path)
    checklist = db_session.query(Checklist).one()
    egret = _observation_named(db_session, checklist, "Snowy Egret")
    match = _confirmed_match(db_session, checklist, egret, note="distant, low confidence")

    result = import_ebird_csv(db_session, csv_path)  # cumulative re-upload
    db_session.refresh(match)

    assert match.observation_id is not None
    relinked = db_session.get(Observation, match.observation_id)
    assert relinked is not None
    assert relinked.common_name == "Snowy Egret"
    assert relinked.checklist_id == checklist.id
    assert match.note == "distant, low confidence"
    assert match.reviewed_at is not None
    assert result["matches_relinked"] == 1
    assert result["matches_unlinked"] == 0


def test_reimport_does_not_duplicate_observations(db_session, tmp_path):
    """Pre-existing behavior (the reason delete-and-recreate exists):
    re-uploading must not inflate species counts."""
    csv_path = _write_csv(tmp_path, "history.csv", [
        _row("S1", "Snowy Egret", "Egretta thula"),
        _row("S1", "Mallard", "Anas platyrhynchos"),
    ])
    import_ebird_csv(db_session, csv_path)
    import_ebird_csv(db_session, csv_path)
    import_ebird_csv(db_session, csv_path)
    assert db_session.query(Observation).count() == 2


def test_cumulative_upload_with_new_checklist_preserves_old_links(db_session, tmp_path):
    first = _write_csv(tmp_path, "first.csv", [_row("S1", "Snowy Egret", "Egretta thula")])
    import_ebird_csv(db_session, first)
    checklist = db_session.query(Checklist).one()
    match = _confirmed_match(db_session, checklist, _observation_named(db_session, checklist, "Snowy Egret"))

    second = _write_csv(tmp_path, "second.csv", [
        _row("S1", "Snowy Egret", "Egretta thula"),
        _row("S2", "Mallard", "Anas platyrhynchos", date="20 Jun 2026"),
    ])
    result = import_ebird_csv(db_session, second)
    db_session.refresh(match)

    assert result["checklists_created"] == 1
    assert db_session.get(Observation, match.observation_id).common_name == "Snowy Egret"


def test_species_removed_from_checklist_is_reported_not_silent(db_session, tmp_path):
    """If a person edited the checklist on eBird and the species is gone,
    there is nothing valid to link to. The link must clear (a dangling id
    would be worse) AND the result must say so -- #95's other half was
    that the loss came with no error and no warning."""
    before = _write_csv(tmp_path, "before.csv", [
        _row("S1", "Snowy Egret", "Egretta thula"),
        _row("S1", "Mallard", "Anas platyrhynchos"),
    ])
    import_ebird_csv(db_session, before)
    checklist = db_session.query(Checklist).one()
    match = _confirmed_match(db_session, checklist, _observation_named(db_session, checklist, "Snowy Egret"))

    after = _write_csv(tmp_path, "after.csv", [_row("S1", "Mallard", "Anas platyrhynchos")])
    result = import_ebird_csv(db_session, after)
    db_session.refresh(match)

    assert match.observation_id is None
    assert result["matches_relinked"] == 0
    assert result["matches_unlinked"] == 1


def test_fallback_identification_is_untouched_by_reimport(db_session, tmp_path):
    """Fallback IDs (species never on the checklist) live on the Match row
    itself and have no observation to relink."""
    csv_path = _write_csv(tmp_path, "history.csv", [_row("S1", "Mallard", "Anas platyrhynchos")])
    import_ebird_csv(db_session, csv_path)
    checklist = db_session.query(Checklist).one()
    photo = Photo(flickr_id="fb1", date_taken="2026-06-14T07:45:00")
    db_session.add(photo)
    db_session.flush()
    match = Match(
        checklist_id=checklist.id,
        photo_id=photo.id,
        observation_id=None,
        method="manual",
        fallback_common_name="Great Blue Heron",
        reviewed_at=datetime(2026, 6, 15, 9, 0),
    )
    db_session.add(match)
    db_session.commit()

    result = import_ebird_csv(db_session, csv_path)
    db_session.refresh(match)

    assert match.fallback_common_name == "Great Blue Heron"
    assert match.observation_id is None
    assert result["matches_unlinked"] == 0


def test_first_import_keeps_every_species_on_a_new_checklist(db_session, tmp_path):
    """Found while writing the #95 tests: the importer's re-import branch
    used to fire on the *second row* of a brand-new checklist, deleting
    the first row's observation -- so a 3-species checklist imported as 2
    while the result still reported 3 created."""
    csv_path = _write_csv(tmp_path, "history.csv", [
        _row("S1", "Snowy Egret", "Egretta thula"),
        _row("S1", "Mallard", "Anas platyrhynchos"),
        _row("S1", "Wood Duck", "Aix sponsa"),
    ])
    result = import_ebird_csv(db_session, csv_path)

    names = sorted(o.common_name for o in db_session.query(Observation))
    assert names == ["Mallard", "Snowy Egret", "Wood Duck"]
    assert result["observations_created"] == 3

"""HTTP-level regression tests for the 2026-10-13 code review's H1.

The bug: the match endpoints created or logged rows keyed by a photo id without
checking the photo existed, and SQLite was not enforcing foreign keys. One request
with an unknown photo id returned HTTP 500 *and* saved a Match pointing at nothing;
from then on GET /outings/{id} returned 500 permanently, and re-running the matcher
did not repair it (the row's method was "manual").

These tests drive the real FastAPI app through its HTTP interface (the routers had
no HTTP-level tests at all). They use an in-memory database, set up in conftest.py.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, enable_sqlite_foreign_keys, engine as app_engine, get_db
from app.main import app
from app.models import AiSuggestionLog, Checklist, Match, Observation, Photo

MISSING_PHOTO_ID = 999_999


@pytest.fixture()
def world():
    """A fresh in-memory database with one outing (one checklist, one species, one
    real photo), wired into the app. Foreign keys are enforced, as in production."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    with Session() as db:
        checklist = Checklist(
            submission_id="S1", location_name="Lake Merritt", date="2026-06-14",
            start_time="07:30 AM", duration_minutes=60,
        )
        db.add(checklist)
        db.flush()
        observation = Observation(checklist_id=checklist.id, common_name="Mallard")
        photo = Photo(flickr_id="f1", title="Mallard", date_taken="2026-06-14T07:45:00")
        db.add_all([observation, photo])
        db.flush()
        ids = {"checklist": checklist.id, "observation": observation.id, "photo": photo.id}
        db.commit()

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, Session, ids
    app.dependency_overrides.clear()


def _counts(Session):
    with Session() as db:
        return db.query(Match).count(), db.query(AiSuggestionLog).count()


def _post(client, path, json):
    return client.post(path, json=json)


@pytest.mark.parametrize(
    "endpoint, body_for",
    [
        ("assign", lambda ids: {"observation_id": ids["observation"], "note": None}),
        ("accept", lambda ids: {"observation_id": ids["observation"], "confidence": 0.9,
                                "suggested_common_name": "Mallard"}),
        ("accept-fallback", lambda ids: {"common_name": "Mallard", "confidence": 0.8}),
        ("reject", lambda ids: {"suggested_common_name": "Mallard", "confidence": 0.5}),
    ],
)
def test_unknown_photo_id_is_a_404_and_writes_nothing(world, endpoint, body_for):
    client, Session, ids = world
    before = _counts(Session)

    response = _post(
        client, f"/match/{ids['checklist']}/{endpoint}/{MISSING_PHOTO_ID}", body_for(ids)
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Photo not found"
    assert _counts(Session) == before, "a rejected request must not leave any row behind"


def test_a_rejected_bad_request_does_not_break_the_outing_page(world):
    """The original symptom: after one bad POST, GET /outings/{id} returned 500 for good."""
    client, Session, ids = world
    assert client.get(f"/outings/{ids['checklist']}").status_code == 200

    client.post(
        f"/match/{ids['checklist']}/assign/{MISSING_PHOTO_ID}",
        json={"observation_id": ids["observation"], "note": None},
    )

    assert client.get(f"/outings/{ids['checklist']}").status_code == 200
    assert client.get("/outings").status_code == 200


def test_a_real_photo_can_still_be_assigned(world):
    """The fix must not over-block: a valid request still works end to end."""
    client, Session, ids = world

    response = _post(
        client,
        f"/match/{ids['checklist']}/assign/{ids['photo']}",
        {"observation_id": ids["observation"], "note": "close-up"},
    )

    assert response.status_code == 200
    assert response.json()["method"] == "manual"
    with Session() as db:
        match = db.query(Match).one()
        assert (match.photo_id, match.observation_id, match.note) == (
            ids["photo"], ids["observation"], "close-up",
        )


def test_database_itself_refuses_a_match_for_a_missing_photo(world):
    """Defense in depth: even if a handler forgets the check, the database says no."""
    _, Session, ids = world
    with Session() as db:
        db.add(Match(checklist_id=ids["checklist"], photo_id=MISSING_PHOTO_ID))
        with pytest.raises(IntegrityError):
            db.commit()


def test_the_real_engine_enforces_foreign_keys():
    """The engine the app actually uses (not a test one) must have enforcement on."""
    with app_engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1

"""Shared test setup.

DATABASE_URL is pointed at an in-memory database *before* anything imports the
app. app.db builds its engine, and app.main creates tables on it, at import time
from this setting. Left alone, an HTTP-level test that imports the app would
touch whatever database the developer's own environment points at, which for a
real user is their real data. So: set it here, then refuse to run if it didn't
take effect.
"""
import os

os.environ["DATABASE_URL"] = "sqlite://"

from app.config import settings  # noqa: E402  (must come after the line above)

assert settings.database_url == "sqlite://", (
    "Refusing to run tests: the app is configured with a real database "
    f"({settings.database_url!r}). Tests must only ever use an in-memory one."
)


# ---- shared fixture: one outing, in an in-memory database, wired into the app ----------
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import Base, enable_sqlite_foreign_keys, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Checklist, Observation, Photo  # noqa: E402


@pytest.fixture()
def world():
    """A fresh in-memory database with one outing (one checklist, one species, one
    real photo that has an image URL), wired into the app. Foreign keys are enforced,
    as in production. Yields (client, Session, ids)."""
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
        photo = Photo(
            flickr_id="f1", title="Mallard", date_taken="2026-06-14T07:45:00",
            url_medium="https://example.invalid/f1.jpg",
        )
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

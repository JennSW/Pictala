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

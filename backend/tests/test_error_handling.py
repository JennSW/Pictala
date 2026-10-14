"""Errors must reach the person readable, with something they can try.

Found in a fresh-install test on 2026-10-13: pressing "Sync now" with no Flickr
account set up made the server crash with a plain 500. That response carried no
CORS headers, so the browser hid it and the page said "Failed to fetch -- is the
backend running?" while the backend was running fine. These tests drive the real
app and check every kind of failure comes back as {"detail", "hint", "error_id"},
readable by the browser, with no traceback.
"""
import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db

from app.errors import (
    BadInputError,
    ExternalServiceError,
    NotConfiguredError,
    PictalaError,
)
from app.main import app

ORIGIN = {"Origin": "http://localhost:5173"}


def _raise(exc):
    def endpoint():
        raise exc

    return endpoint


@pytest.fixture()
def boom():
    """Mount a throwaway route on the real app that raises whatever a test asks for."""
    added = []

    def mount(path, exc):
        app.add_api_route(path, _raise(exc), methods=["GET"])
        added.append(path)

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, mount
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) not in added]


def test_an_unexpected_crash_is_readable_by_the_browser_and_has_a_reference(boom):
    client, mount = boom
    mount("/__boom", RuntimeError("secret internal detail: /Users/someone/db.sqlite"))
    r = client.get("/__boom", headers=ORIGIN)
    assert r.status_code == 500
    body = r.json()
    assert body["detail"] == "Something went wrong on the server."
    assert body["hint"] and "backend.log" in body["hint"]
    assert len(body["error_id"]) == 8
    # The browser can only read this response if CORS headers are on it (the original bug).
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    # Nothing internal leaks to the page.
    assert "secret internal detail" not in r.text and "Traceback" not in r.text


def test_the_crash_is_logged_under_the_same_reference(boom, caplog):
    client, mount = boom
    mount("/__boom2", RuntimeError("kaboom"))
    with caplog.at_level("ERROR", logger="pictala"):
        error_id = client.get("/__boom2").json()["error_id"]
    assert any(error_id in rec.getMessage() for rec in caplog.records)
    assert any(rec.exc_info for rec in caplog.records), "the traceback belongs in the log"


@pytest.mark.parametrize(
    "exc, status",
    [
        (NotConfiguredError("Flickr isn't set up yet.", "Run the setup script."), 400),
        (BadInputError("That file isn't an eBird export.", "Download it from eBird."), 400),
        (ExternalServiceError("Flickr said no.", "Check your key."), 502),
        (PictalaError("Custom.", "Do this.", status_code=418), 418),
    ],
)
def test_pictala_errors_keep_their_message_hint_and_status(boom, exc, status):
    client, mount = boom
    mount("/__known", exc)
    r = client.get("/__known", headers=ORIGIN)
    assert r.status_code == status
    assert r.json() == {"detail": exc.message, "hint": exc.hint, "error_id": None}
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.parametrize(
    "exc, status, words",
    [
        (requests.exceptions.ConnectionError("dns"), 503, "internet connection"),
        (requests.exceptions.Timeout("slow"), 503, "too long"),
    ],
)
def test_network_failures_say_to_check_the_connection(boom, exc, status, words):
    client, mount = boom
    mount("/__net", exc)
    r = client.get("/__net", headers=ORIGIN)
    assert r.status_code == status
    body = r.json()
    assert words in (body["detail"] + " " + body["hint"])
    assert body["error_id"] is None, "an expected failure is not a bug, so it gets no bug reference"


def test_an_outside_service_refusing_us_points_at_the_api_keys(boom):
    client, mount = boom
    response = requests.Response()
    response.status_code = 403
    mount("/__http", requests.exceptions.HTTPError("403", response=response))
    r = client.get("/__http")
    assert r.status_code == 502
    assert "HTTP 403" in r.json()["detail"]
    assert "backend/.env" in r.json()["hint"]


@pytest.fixture()
def empty_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield
    app.dependency_overrides.clear()


def test_normal_http_errors_keep_their_detail_and_gain_the_same_shape(empty_db):
    with TestClient(app) as client:
        r = client.get("/outings/987654")
    assert r.status_code == 404
    assert r.json() == {"detail": "Outing not found", "hint": None, "error_id": None}


def test_a_malformed_request_gets_a_sentence_not_a_list():
    with TestClient(app) as client:
        r = client.post("/match/1/assign/1", json={"nope": True})
    assert r.status_code == 422
    body = r.json()
    assert isinstance(body["detail"], str) and "observation_id" in body["detail"]
    assert body["hint"]


def test_an_unknown_origin_still_cannot_read_errors(boom):
    """Making errors readable must not widen who can read them."""
    client, mount = boom
    mount("/__x", RuntimeError("x"))
    r = client.get("/__x", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers

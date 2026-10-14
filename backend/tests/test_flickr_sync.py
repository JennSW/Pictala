"""Flickr sync must fetch every page of results (code review 2026-10-13, H2).

The client used to ask for 500 photos and never request a second page, so a date
range holding more than 500 photos lost the rest with no error. These tests fake
Flickr's responses (no network, no credentials) and check the client follows all
pages, keeps each photo once, and refuses to return a partial list.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, enable_sqlite_foreign_keys, get_db
from app.errors import BadInputError, ExternalServiceError, NotConfiguredError
from app.main import app
from app.models import Photo, SyncLog
from app.services import flickr_client


def _configure_flickr(monkeypatch):
    """Pretend Flickr is set up (the real settings come from the developer's own .env)."""
    for attr in ("flickr_api_key", "flickr_api_secret", "flickr_oauth_token",
                 "flickr_oauth_token_secret", "flickr_user_id"):
        monkeypatch.setattr(flickr_client.settings, attr, "test-value")


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _photo(photo_id):
    return {"id": photo_id, "title": f"photo {photo_id}", "tags": "", "datetaken": "2026-06-14 08:00:00",
            "latitude": "0", "longitude": "0", "url_m": f"https://example.invalid/{photo_id}.jpg"}


def _page(pages, page, ids):
    return {"stat": "ok", "photos": {"page": page, "pages": pages, "perpage": 500,
                                     "total": "n/a", "photo": [_photo(i) for i in ids]}}


@pytest.fixture()
def fake_flickr(monkeypatch):
    """Serve scripted pages and record every request's params."""
    calls = []
    script = {}

    def fake_get(url, params=None, auth=None, timeout=None):
        calls.append(dict(params))
        return _FakeResponse(script[params["page"]] if params["page"] in script else script["default"])

    monkeypatch.setattr(flickr_client.requests, "get", fake_get)
    monkeypatch.setattr(flickr_client, "_oauth", lambda: None)
    _configure_flickr(monkeypatch)
    return calls, script


def test_a_single_page_makes_a_single_request(fake_flickr):
    calls, script = fake_flickr
    script[1] = _page(1, 1, ["a", "b"])
    photos = flickr_client.get_photos_in_range("2026-06-14", "2026-06-14")
    assert [p["id"] for p in photos] == ["a", "b"]
    assert [c["page"] for c in calls] == [1]


def test_every_page_is_fetched_in_order(fake_flickr):
    calls, script = fake_flickr
    script[1] = _page(3, 1, ["a1", "a2"])
    script[2] = _page(3, 2, ["b1", "b2"])
    script[3] = _page(3, 3, ["c1"])
    photos = flickr_client.get_photos_in_range("2026-06-01", "2026-06-30")
    assert [p["id"] for p in photos] == ["a1", "a2", "b1", "b2", "c1"]
    assert [c["page"] for c in calls] == [1, 2, 3]


def test_no_results_is_an_empty_list(fake_flickr):
    calls, script = fake_flickr
    script[1] = _page(0, 1, [])  # Flickr reports pages=0 when nothing matches
    assert flickr_client.get_photos_in_range("2026-06-14", "2026-06-14") == []
    assert len(calls) == 1


def test_page_counts_sent_as_strings_are_understood(fake_flickr):
    calls, script = fake_flickr
    script[1] = _page("2", 1, ["a"])
    script[2] = _page("2", 2, ["b"])
    assert [p["id"] for p in flickr_client.get_photos_in_range("2026-06-01", "2026-06-30")] == ["a", "b"]


def test_a_photo_seen_on_two_pages_is_returned_once(fake_flickr):
    """New uploads between requests can shift the ordering, repeating a photo on the
    next page. The caller inserts without flushing, so a repeat would crash the sync."""
    calls, script = fake_flickr
    script[1] = _page(2, 1, ["a", "b"])
    script[2] = _page(2, 2, ["b", "c"])
    assert [p["id"] for p in flickr_client.get_photos_in_range("2026-06-01", "2026-06-30")] == ["a", "b", "c"]


def test_a_range_over_the_page_limit_raises_instead_of_truncating(fake_flickr):
    calls, script = fake_flickr
    script["default"] = _page(flickr_client.MAX_PAGES + 5, 1, ["x"])
    with pytest.raises(BadInputError) as caught:
        flickr_client.get_photos_in_range("2020-01-01", "2026-12-31")
    assert "Narrow the date range" in caught.value.hint
    assert len(calls) == flickr_client.MAX_PAGES, "must stop at the cap, not keep fetching"


def test_the_same_date_filters_are_sent_on_every_page(fake_flickr):
    calls, script = fake_flickr
    script[1] = _page(2, 1, ["a"])
    script[2] = _page(2, 2, ["b"])
    flickr_client.get_photos_in_range("2026-06-14", "2026-06-14")  # bare dates: must be widened to a full day
    assert {(c["min_taken_date"], c["max_taken_date"]) for c in calls} == {
        ("2026-06-14 00:00:00", "2026-06-14 23:59:59")
    }


@pytest.mark.parametrize(
    "code, says, hint_has",
    [
        (100, "rejected your API key", "FLICKR_API_KEY"),
        (98, "didn't accept your authorization", "flickr_oauth_setup"),
        (96, "didn't accept your authorization", "flickr_oauth_setup"),
        (1, "couldn't find that user", "FLICKR_USER_ID"),
        (105, "temporarily unavailable", "few minutes"),
        (4242, "Something odd", "backend/.env"),  # a code we don't know: still includes Flickr's words
    ],
)
def test_flickr_error_codes_say_what_to_fix(fake_flickr, code, says, hint_has):
    calls, script = fake_flickr
    script[1] = {"stat": "fail", "code": code, "message": "Something odd"}
    with pytest.raises(ExternalServiceError) as caught:
        flickr_client.get_photos_in_range("2026-06-14", "2026-06-14")
    assert says in caught.value.message
    assert hint_has in caught.value.hint


def test_an_unconfigured_flickr_is_explained_before_any_request_is_made(monkeypatch):
    calls = []
    monkeypatch.setattr(flickr_client.requests, "get", lambda *a, **k: calls.append(1))
    for attr in ("flickr_api_key", "flickr_api_secret", "flickr_oauth_token",
                 "flickr_oauth_token_secret", "flickr_user_id"):
        monkeypatch.setattr(flickr_client.settings, attr, "")
    with pytest.raises(NotConfiguredError) as caught:
        flickr_client.get_photos_in_range("2026-06-14", "2026-06-14")
    assert "FLICKR_API_KEY" in caught.value.hint and "flickr_oauth_setup" in caught.value.hint
    assert "eBird CSV" in caught.value.hint, "newcomers should be told what still works without Flickr"
    assert calls == [], "no request should reach Flickr with an empty key"


# ---- through the real HTTP endpoint -------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(flickr_client, "_oauth", lambda: None)
    _configure_flickr(monkeypatch)
    monkeypatch.setattr("app.routers.sync._try_get_utc_offset", lambda flickr_id: None)  # would call Flickr
    with TestClient(app) as c:
        yield c, Session
    app.dependency_overrides.clear()


def test_sync_stores_photos_from_every_page_without_crashing_on_a_repeat(client, monkeypatch):
    c, Session = client
    pages = {1: _page(2, 1, ["a", "b"]), 2: _page(2, 2, ["b", "c"])}  # "b" repeats across pages
    monkeypatch.setattr(
        flickr_client.requests, "get",
        lambda url, params=None, auth=None, timeout=None: _FakeResponse(pages[params["page"]]),
    )
    response = c.post("/sync/flickr", params={"min_taken_date": "2026-06-01", "max_taken_date": "2026-06-30"})
    assert response.status_code == 200
    assert response.json()["photos_created"] == 3
    with Session() as db:
        assert sorted(p.flickr_id for p in db.query(Photo).all()) == ["a", "b", "c"]


def test_an_oversized_range_comes_back_as_a_readable_error_not_a_bare_500(client, monkeypatch):
    c, Session = client
    monkeypatch.setattr(
        flickr_client.requests, "get",
        lambda url, params=None, auth=None, timeout=None: _FakeResponse(_page(flickr_client.MAX_PAGES + 5, 1, ["x"])),
    )
    response = c.post("/sync/flickr", params={"min_taken_date": "2020-01-01", "max_taken_date": "2026-12-31"})
    assert response.status_code == 400
    assert "Narrow the date range" in response.json()["hint"]
    with Session() as db:
        assert db.query(Photo).count() == 0, "a refused sync must not store a partial result"


def test_sync_now_without_flickr_explains_itself_and_does_not_use_up_a_sync(client, monkeypatch):
    """The fresh-install finding: this used to be a bare 500 that still used one of the
    day's four syncs, and the page blamed the backend being down."""
    c, Session = client
    for attr in ("flickr_api_key", "flickr_api_secret", "flickr_oauth_token",
                 "flickr_oauth_token_secret", "flickr_user_id"):
        monkeypatch.setattr(flickr_client.settings, attr, "")
    response = c.post("/sync/run", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 400
    body = response.json()
    assert "isn't connected" in body["detail"] and "flickr_oauth_setup" in body["hint"]
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    with Session() as db:
        assert db.query(SyncLog).count() == 0, "a sync that could not start must not be counted"

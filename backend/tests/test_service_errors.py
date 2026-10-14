"""Failures in the services Pictala depends on must say what to do about them.

Each of these used to surface as a bare "Internal Server Error" or "502 Bad Gateway"
with no reason (issue #96 was exactly this for Anthropic). Here Anthropic's and eBird's
replies are faked, so nothing touches the network and no key is ever used.
"""
import pytest
import requests

from app.services import ebird_taxonomy, species_classifier

ORIGIN = {"Origin": "http://localhost:5173"}
SECRET = "sk-ant-THIS-MUST-NEVER-APPEAR-IN-A-RESPONSE"


class _Reply:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._body = body
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


@pytest.fixture()
def anthropic(monkeypatch):
    """Configure a (fake) Anthropic key and let each test script the reply."""
    monkeypatch.setattr(species_classifier.settings, "anthropic_api_key", SECRET)
    monkeypatch.setattr(species_classifier, "_fetch_image_as_base64", lambda url: ("AAAA", "image/jpeg"))
    reply = {}
    monkeypatch.setattr(
        species_classifier.requests, "post", lambda *a, **k: reply["value"]()
    )
    return reply


def _suggest(world):
    client, _, ids = world
    return client.post(
        f"/match/{ids['checklist']}/suggest-fallback/{ids['photo']}", headers=ORIGIN
    )


def test_ai_suggestions_without_a_key_explain_how_to_add_one(world, monkeypatch):
    monkeypatch.setattr(species_classifier.settings, "anthropic_api_key", "")
    r = _suggest(world)
    assert r.status_code == 400
    assert "Anthropic API key" in r.json()["detail"]
    assert "ANTHROPIC_API_KEY" in r.json()["hint"] and "pick the species by hand" in r.json()["hint"]
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.parametrize(
    "status, body, says, hint_has",
    [
        (401, {"error": {"type": "authentication_error", "message": "invalid x-api-key"}},
         "didn't accept your API key", "ANTHROPIC_API_KEY"),
        (400, {"error": {"type": "invalid_request_error",
                         "message": "key is not scoped to a workspace"}},
         "key is not scoped to a workspace", "ANTHROPIC_MODEL"),
        (429, {"error": {"type": "rate_limit_error", "message": "slow down"}},
         "limiting how fast", "console.anthropic.com"),
        (503, None, "having trouble", "few minutes"),
    ],
)
def test_anthropic_refusals_say_why_and_what_to_try(world, anthropic, status, body, says, hint_has):
    anthropic["value"] = lambda: _Reply(status, body, {"request-id": "req_123"})
    r = _suggest(world)
    assert r.status_code == 502
    payload = r.json()
    assert says in payload["detail"]
    assert hint_has in payload["hint"]
    assert SECRET not in r.text, "the API key must never reach a response"


def test_anthropic_being_unreachable_says_to_check_the_connection(world, anthropic):
    def down():
        raise requests.exceptions.ConnectionError("no route")

    anthropic["value"] = down
    r = _suggest(world)
    assert r.status_code == 502 and "internet connection" in r.json()["hint"]


def test_the_real_anthropic_reason_is_logged_without_the_key(world, anthropic, caplog):
    """Issue #96: the log used to say only '502 Bad Gateway'."""
    anthropic["value"] = lambda: _Reply(
        400, {"error": {"type": "invalid_request_error", "message": "needs workspace id"}},
        {"request-id": "req_abc"},
    )
    with caplog.at_level("WARNING", logger="pictala"):
        _suggest(world)
    text = " ".join(rec.getMessage() for rec in caplog.records)
    assert "needs workspace id" in text and "req_abc" in text and SECRET not in text


@pytest.mark.parametrize("value, expected", [(0.7, 0.7), ("0.4", 0.4), ("high", 0.0),
                                             (None, 0.0), (1.9, 1.0), (-3, 0.0)])
def test_a_strange_confidence_from_the_model_cannot_crash_the_request(value, expected):
    assert species_classifier._as_confidence(value) == expected


def test_too_many_photos_for_one_batch_says_how_many_are_allowed():
    with pytest.raises(species_classifier.BadInputError) as caught:
        species_classifier.guess_species_unconstrained_batch(
            [{"photo_id": i, "url": "u", "title": None, "tags": None}
             for i in range(species_classifier.MAX_BATCH_SIZE + 1)]
        )
    assert str(species_classifier.MAX_BATCH_SIZE) in caught.value.hint


# ---- eBird key (used to resolve typed or suggested species names) -----------------------

@pytest.fixture()
def fresh_taxonomy(monkeypatch):
    monkeypatch.setattr(ebird_taxonomy, "_TAXONOMY_CACHE", None)


def _accept_fallback(world):
    client, _, ids = world
    # a name that is NOT on the outing's checklist, so the app must ask eBird's taxonomy
    return client.post(
        f"/match/{ids['checklist']}/accept-fallback/{ids['photo']}",
        json={"common_name": "Great Blue Heron", "confidence": 0.8}, headers=ORIGIN,
    )


def test_naming_a_species_without_an_ebird_key_explains_how_to_get_one(world, fresh_taxonomy, monkeypatch):
    monkeypatch.setattr(ebird_taxonomy.settings, "ebird_api_key", "")
    r = _accept_fallback(world)
    assert r.status_code == 400
    assert "eBird API key" in r.json()["detail"]
    assert "ebird.org/api/keygen" in r.json()["hint"] and "EBIRD_API_KEY" in r.json()["hint"]


def test_an_ebird_key_that_is_rejected_says_to_recheck_it(world, fresh_taxonomy, monkeypatch):
    monkeypatch.setattr(ebird_taxonomy.settings, "ebird_api_key", "wrong")
    monkeypatch.setattr(ebird_taxonomy.requests, "get", lambda *a, **k: _Reply(403))
    r = _accept_fallback(world)
    assert r.status_code == 502
    assert "didn't accept your API key" in r.json()["detail"] and "EBIRD_API_KEY" in r.json()["hint"]

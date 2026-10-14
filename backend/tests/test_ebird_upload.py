"""Uploading an eBird export must work on the files people actually have, and say
what to do when the file is wrong.

eBird emails "Download My Data" as a .zip, spreadsheet programs add a hidden byte-order
mark, and people sometimes pick the wrong file. All of those used to end in a crash or a
silently empty import. These tests go through the real /sync/ebird endpoint.
"""
import io
import tempfile
import zipfile
from pathlib import Path

import pytest

from app.models import Checklist, Observation
from app.services import ebird_import

HEADER = (
    "Submission ID,Common Name,Scientific Name,Count,Location,Location ID,"
    "Latitude,Longitude,Date,Time,Duration (Min)\n"
)
GOOD = HEADER + "S100,Mallard,Anas platyrhynchos,2,Lake Merritt,L1,37.8,-122.2,14 Jun 2026,07:30,60\n"
ORIGIN = {"Origin": "http://localhost:5173"}


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _upload(world, data: bytes, name="MyEBirdData.csv"):
    client, _, _ = world
    return client.post("/sync/ebird", files={"file": (name, data)}, headers=ORIGIN)


def _counts(world):
    _, Session, _ = world
    with Session() as db:
        return db.query(Checklist).count(), db.query(Observation).count()


def test_a_plain_csv_imports(world):
    before = _counts(world)
    r = _upload(world, GOOD.encode())
    assert r.status_code == 200
    assert _counts(world) == (before[0] + 1, before[1] + 1)


def test_the_zip_ebird_emails_you_imports_without_unzipping_it_first(world):
    r = _upload(world, _zip({"MyEBirdData.csv": GOOD.encode()}), name="MyEBirdData.zip")
    assert r.status_code == 200
    assert r.json()["checklists_created"] == 1


def test_mac_zip_clutter_is_ignored(world):
    data = _zip({"__MACOSX/._MyEBirdData.csv": b"\x00junk", "MyEBirdData.csv": GOOD.encode()})
    assert _upload(world, data, name="export.zip").status_code == 200


def test_a_byte_order_mark_does_not_hide_the_columns(world):
    r = _upload(world, b"\xef\xbb\xbf" + GOOD.encode())
    assert r.status_code == 200 and r.json()["checklists_created"] == 1


@pytest.mark.parametrize(
    "data, name, detail_has, hint_has",
    [
        (b"", "x.csv", "empty", "Download My Data"),
        (HEADER.encode()[:0] + b"colour,shape\nred,round\n", "x.csv", "doesn't look like an eBird export", "Common Name"),
        (b"\xff\xfe\x00\x81\x82 not text \xff", "photo.jpg", "couldn't be read as a text CSV", "Download My Data"),
        (b"PK\x03\x04 cut short", "x.zip", "couldn't be opened", "Download it again"),
        (_zip({"notes.txt": b"hello"}), "x.zip", "doesn't contain a CSV", "MyEBirdData.csv"),
    ],
)
def test_the_wrong_file_gets_a_reason_and_a_next_step(world, data, name, detail_has, hint_has):
    before = _counts(world)
    r = _upload(world, data, name=name)
    assert r.status_code == 400
    assert detail_has in r.json()["detail"]
    assert hint_has in r.json()["hint"]
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert _counts(world) == before, "a rejected file must not change anything"


def test_an_oversized_upload_is_refused_with_its_limit(world, monkeypatch):
    monkeypatch.setattr(ebird_import, "MAX_UPLOAD_BYTES", 100)
    r = _upload(world, GOOD.encode() * 5)
    assert r.status_code == 400 and "50 MB" in r.json()["detail"]


def test_one_row_with_a_bad_latitude_does_not_sink_the_import(world):
    bad = HEADER + "S9,Mallard,Anas platyrhynchos,1,Lake Merritt,L1,north,-122.2,14 Jun 2026,07:30,60\n"
    r = _upload(world, bad.encode())
    assert r.status_code == 200
    _, Session, _ = world
    with Session() as db:
        assert db.query(Checklist).filter_by(submission_id="S9").one().latitude is None


def test_no_copy_of_the_upload_is_left_in_the_temp_folder(world, monkeypatch, tmp_path):
    """The upload is someone's whole birding history (code review 2026-10-13, M4)."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    ok = _upload(world, GOOD.encode())
    bad = _upload(world, b"colour,shape\nred,round\n")
    assert (ok.status_code, bad.status_code) == (200, 400)
    assert list(Path(tmp_path).iterdir()) == []

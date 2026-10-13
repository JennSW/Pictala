"""start.sh must only load the invented sample data into an EMPTY database.

It runs against whatever database the backend is configured to use, which on a
real machine is the person's own data. Loading invented outings into it would
mix them in with real ones (found in the 2026-10-13 code review, M1).

These tests run the real shell function, extracted from start.sh between its
BEGIN/END markers, against a tiny local HTTP server that records what it is asked
to do -- so they exercise the actual code, not a copy of it.
"""
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("curl") is None,
    reason="needs bash and curl",
)


def _seed_function_source() -> str:
    text = (REPO_ROOT / "start.sh").read_text(encoding="utf-8")
    begin = text.index("# BEGIN seed_sample_data")
    end = text.index("# END seed_sample_data")
    return text[begin:end]


class _FakeBackend:
    """Answers GET /outings with a fixed body and records every request."""

    def __init__(self, outings_body: str):
        self.requests: list[tuple[str, str]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _record(self):
                outer.requests.append((self.command, self.path))

            def do_GET(self):
                self._record()
                body = outings_body.encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                self._record()
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):  # keep test output quiet
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def _run_seed_step(port: int) -> subprocess.CompletedProcess:
    script = (
        "set -euo pipefail\n"
        f"BACKEND_PORT={port}\n"
        + _seed_function_source()
        + "\nseed_sample_data_if_empty\n"
    )
    return subprocess.run(
        ["bash", "-c", script],
        cwd=BACKEND_DIR,  # start.sh runs this step from backend/, where seed_data/ lives
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_sample_data_is_loaded_into_an_empty_database():
    with _FakeBackend("[]") as fake:
        result = _run_seed_step(fake.port)
    assert result.returncode == 0
    assert ("POST", "/sync/ebird") in fake.requests
    assert ("POST", "/sync/match") in fake.requests


def test_sample_data_is_never_loaded_into_a_database_that_has_outings():
    existing = '[{"id": 114, "location_name": "Somewhere", "date": "2026-09-17"}]'
    with _FakeBackend(existing) as fake:
        result = _run_seed_step(fake.port)
    assert result.returncode == 0
    posts = [r for r in fake.requests if r[0] == "POST"]
    assert posts == [], f"start.sh must not write to a database that already has data: {posts}"
    assert "already has data" in result.stdout


def test_nothing_is_loaded_when_the_backend_cannot_be_checked():
    """If the emptiness check can't be made, not loading is the safe direction."""
    import socket

    with socket.socket() as s:  # find a port with nothing listening on it
        s.bind(("127.0.0.1", 0))
        closed_port = s.getsockname()[1]
    result = _run_seed_step(closed_port)
    assert result.returncode == 0
    assert "Loading sample eBird data" not in result.stdout

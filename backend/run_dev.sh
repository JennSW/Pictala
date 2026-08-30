#!/bin/sh
# Runs uvicorn with backend/ as cwd, so .env and the sqlite DB path resolve correctly.
cd "$(dirname "$0")" || exit 1
exec .venv/bin/uvicorn app.main:app --reload --port 8000

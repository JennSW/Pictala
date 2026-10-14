#!/usr/bin/env bash
# start.sh — one-command way to run Pictala locally on your Mac.
#
# What this does, in order:
#   1. Checks you have Python 3 and Node.js installed (tells you how to get
#      them if not, and stops — it will not install anything system-wide
#      without you seeing exactly what it's doing).
#   2. Sets up the backend (installs its Python packages into a private
#      folder just for this app, so it can't affect anything else on your
#      Mac) and starts it.
#   3. Loads the sample eBird data that ships with this app, so you have
#      something to look at immediately — no real accounts needed yet.
#   4. Sets up the frontend (installs its packages) and starts it.
#   5. Opens the app in your browser.
#
# You can stop everything by pressing Ctrl+C in this window.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

BACKEND_PORT=8000
FRONTEND_PORT=5173

# ---- Step 1: check prerequisites -------------------------------------------
echo "Checking for required tools..."

# This app's code uses Python's modern "float | None" style type hints,
# which only work on Python 3.10 or newer. Macs often have an old Python
# 3.9 pre-installed (bundled with Xcode's command line tools) as the
# default `python3` on PATH, so we specifically look for a 3.10+ version
# rather than just taking whatever `python3` resolves to.
find_good_python() {
  for candidate in python3.13 python3.12 python3.11 python3.10; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  if command -v python3 >/dev/null 2>&1; then
    minor="$(python3 -c 'import sys; print(sys.version_info[1])' 2>/dev/null || echo 0)"
    if [ "$minor" -ge 10 ] 2>/dev/null; then
      echo "python3"
      return 0
    fi
  fi
  return 1
}

PYTHON_BIN="$(find_good_python || true)"
if [ -z "$PYTHON_BIN" ]; then
  cat <<'EOF'

This app needs Python 3.10 or newer, and your Mac's python3 is either
missing or too old (this is common — Macs often ship with an old Python
3.9 bundled with Xcode's command line tools, which isn't the same thing).

Easiest fix: install Homebrew (https://brew.sh) if you don't have it, then run:
  brew install python@3.12

Or download a current version directly from https://www.python.org/downloads/

Once that's done, run this script again: ./start.sh
EOF
  exit 1
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  cat <<'EOF'

Node.js isn't installed (or isn't on your PATH).

Easiest fix: install Homebrew (https://brew.sh) if you don't have it, then run:
  brew install node

Or download it directly from https://nodejs.org (choose the LTS version).

Once that's done, run this script again: ./start.sh
EOF
  exit 1
fi

echo "  Python: $("$PYTHON_BIN" --version) (using '$PYTHON_BIN')"
echo "  Node.js:  $(node --version)"
echo ""

# ---- Step 2: backend setup --------------------------------------------------
echo "Setting up the backend (this only downloads packages the first time)..."
cd backend

if [ -d ".venv" ]; then
  # If a previous run created this with too old a Python (e.g. the 3.9
  # that ships with Xcode's command line tools), rebuild it with a good one.
  existing_minor="$(.venv/bin/python3 -c 'import sys; print(sys.version_info[1])' 2>/dev/null || echo 0)"
  if [ "$existing_minor" -lt 10 ] 2>/dev/null; then
    echo "  Found an existing virtual environment built with too old a Python version — rebuilding it..."
    rm -rf .venv
  fi
fi
if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi
source .venv/bin/activate
pip install --quiet -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "  Created backend/.env (using sample data for now — no real API keys needed yet)."
fi

echo "Starting the backend server..."
uvicorn app.main:app --port "$BACKEND_PORT" > ../backend.log 2>&1 &
BACKEND_PID=$!

cleanup() {
  echo ""
  echo "Stopping Pictala..."
  kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT

# Wait for the backend to actually be ready before moving on.
echo -n "  Waiting for backend to come up"
for _ in $(seq 1 30); do
  if curl -s "http://localhost:$BACKEND_PORT/health" >/dev/null 2>&1; then
    echo " done."
    break
  fi
  echo -n "."
  sleep 1
done

if ! curl -s "http://localhost:$BACKEND_PORT/health" >/dev/null 2>&1; then
  echo ""
  echo "The backend didn't start. Check backend.log in this folder for details."
  exit 1
fi

# ---- Step 3: load sample data so there's something to see immediately -----
# BEGIN seed_sample_data (kept between markers so tests can run this exact code)
#
# Only ever into an EMPTY database. This script runs against whatever database
# the backend is configured to use -- on a machine that already has real
# outings (the default backend/birdtrip.db, or a DATABASE_URL in backend/.env)
# that is real data, and loading invented sample outings into it would mix
# them in with the real ones. If the check itself fails we also skip: not
# loading is always the safe direction.
seed_sample_data_if_empty() {
  local outings
  outings="$(curl -s "http://localhost:$BACKEND_PORT/outings" || true)"
  if [ "$outings" = "[]" ]; then
    echo "Loading sample eBird data so you have outings to look at right away..."
    curl -s -X POST "http://localhost:$BACKEND_PORT/sync/ebird" \
      -F "file=@seed_data/sample_ebird_export.csv" > /dev/null || true
    curl -s -X POST "http://localhost:$BACKEND_PORT/sync/match" > /dev/null || true
  else
    echo "Your database already has data (or could not be checked), so no sample data was loaded."
  fi
}
# END seed_sample_data
seed_sample_data_if_empty

cd ..

# ---- Step 4: frontend setup -------------------------------------------------
echo "Setting up the frontend (this only downloads packages the first time)..."
cd frontend
if [ ! -d "node_modules" ]; then
  npm install --silent
fi

echo ""
echo "============================================================"
echo " Pictala is starting up."
echo " Your browser will open automatically in a few seconds."
echo " If it doesn't, go to: http://localhost:$FRONTEND_PORT"
echo ""
echo " Backend API docs (optional, for the curious): http://localhost:$BACKEND_PORT/docs"
echo ""
echo " Press Ctrl+C in this window at any time to stop Pictala."
echo "============================================================"
echo ""

# Open the browser once Vite has had a moment to start.
( sleep 3 && open "http://localhost:$FRONTEND_PORT" ) &

npm run dev

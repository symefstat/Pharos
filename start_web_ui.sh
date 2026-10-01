#!/usr/bin/env bash
# Start the Lodestar web UI: FastAPI backend (:8000) + Vite frontend (:5173).
# Run it from anywhere — it cd's to its own directory (the project root).
#
#   ./start_web_ui.sh
#
# Then open the URL it prints (http://localhost:5173). Ctrl-C stops both.

set -euo pipefail

# Resolve the project root = this script's directory, regardless of CWD.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Make sure Homebrew node/npm are on PATH (Vite needs them).
export PATH="/opt/homebrew/bin:$PATH"

PY="$ROOT/venv/bin/python"
[ -x "$PY" ] || PY="python"   # fall back to an already-activated venv

# Free port 8000 if a stray backend is still holding it.
if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "→ Port 8000 in use; stopping the old backend…"
  lsof -nP -tiTCP:8000 -sTCP:LISTEN | xargs kill 2>/dev/null || true
  sleep 1
fi

echo "→ Starting backend (FastAPI) on http://localhost:8000 …"
"$PY" -m uvicorn backend.app.main:app --reload --port 8000 &
BACKEND_PID=$!

# Stop the backend when this script exits (Ctrl-C).
cleanup() { echo; echo "→ Stopping backend…"; kill "$BACKEND_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "→ Starting frontend (Vite). Open the Local URL it prints below."
echo
cd "$ROOT/frontend"
npm run dev

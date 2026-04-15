#!/usr/bin/env bash
# Start the Probabilize server
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing dependencies..."
python -m pip install -r "$SCRIPT_DIR/backend/requirements.txt" -q

echo "Starting server on http://localhost:8000"
UVICORN_ARGS=(backend.app:app --host 127.0.0.1 --port 8000)
if [ "${UVICORN_RELOAD:-0}" = "1" ]; then
  UVICORN_ARGS+=(--reload)
fi
cd "$SCRIPT_DIR" && python -m uvicorn "${UVICORN_ARGS[@]}"

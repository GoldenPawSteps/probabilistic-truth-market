#!/usr/bin/env bash
# Start the Perpetual Probabilistic Truth Market server
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing dependencies..."
pip install -r "$SCRIPT_DIR/backend/requirements.txt" -q

echo "Starting server on http://localhost:8000"
cd "$SCRIPT_DIR" && python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload

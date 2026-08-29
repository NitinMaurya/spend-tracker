#!/usr/bin/env bash
# Start the analyser API and UI together. Everything binds to localhost only (D-029).
set -euo pipefail
cd "$(dirname "$0")"

cleanup() { echo; echo "stopping…"; kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "API → http://127.0.0.1:8787/api/docs"
.venv/bin/python -m analyser.api &

until curl -s --max-time 1 http://127.0.0.1:8787/api/health >/dev/null 2>&1; do sleep 0.5; done
echo "UI  → http://spend-tracker.personal:3111  (or http://localhost:3111)"
( cd ui && npm run dev ) &

wait

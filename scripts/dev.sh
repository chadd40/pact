#!/usr/bin/env bash
# Pact local-first launcher: build the SPA, then run ONE uvicorn process that
# serves the built app + API together in demo clock mode.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Building web app (web/ -> web/dist)"
( cd web && npm install && npm run build )

echo "==> Starting Pact (demo clock) on http://127.0.0.1:8000"
PACT_CLOCK_MODE=demo uv run uvicorn pact.main:app --host 127.0.0.1 --port 8000 "$@"

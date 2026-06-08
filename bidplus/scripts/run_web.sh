#!/usr/bin/env bash
# Start the Bid Intelligence web app (FastAPI + built React UI on port 8000).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUNTIME="${BIDPLUS_RUNTIME_DIR:-$HOME/bidplus-runtime}"
VENV="$RUNTIME/venv"

if [[ ! -x "$VENV/bin/uvicorn" ]]; then
  echo "venv not found at $VENV — run: bash bidplus/scripts/setup_runtime.sh" >&2
  exit 1
fi

UI="$ROOT/frontend"
if [[ ! -f "$UI/dist/index.html" ]]; then
  echo "Building React UI (first time or stale dist)…"
  (cd "$UI" && npm run build)
fi

export BIDPLUS_RUNTIME_DIR="$RUNTIME"
cd "$ROOT"
exec "$VENV/bin/uvicorn" bidplus.web.app:app --host 0.0.0.0 --port 8000

#!/usr/bin/env bash
# S0 runtime bring-up: create the venv + install deps OUTSIDE iCloud, install the
# Chromium browser, and seed the single .env. Idempotent-ish; safe to re-run.
#
#   bash bidplus/scripts/setup_runtime.sh
#
# Honors $BIDPLUS_RUNTIME_DIR (default ~/bidplus-runtime). On macOS it refuses an
# iCloud-synced location, mirroring the bidplus.runtime guard. On Ubuntu the guard
# is a no-op. Override the interpreter with $PYTHON (deploy box pins python3.12).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="${BIDPLUS_RUNTIME_DIR:-$HOME/bidplus-runtime}"

case "$(uname -s)" in
  Darwin)
    case "$RUNTIME_DIR" in
      "$HOME/Documents"/*|"$HOME/Documents"|"$HOME/Desktop"/*|"$HOME/Desktop"|*"Library/Mobile Documents"*)
        echo "ERROR: BIDPLUS_RUNTIME_DIR ($RUNTIME_DIR) is inside iCloud." >&2
        echo "       Pick a path outside ~/Documents and ~/Desktop (e.g. ~/bidplus-runtime)." >&2
        exit 1 ;;
    esac ;;
esac

echo "Repo root  : $REPO_ROOT"
echo "Runtime dir: $RUNTIME_DIR"
mkdir -p "$RUNTIME_DIR"/gem "$RUNTIME_DIR"/hal "$RUNTIME_DIR"/isro

# Prefer the pinned 3.12 (deploy box); fall back to python3 on the dev Mac.
PYTHON="${PYTHON:-python3.12}"
command -v "$PYTHON" >/dev/null 2>&1 || PYTHON="python3"
echo "Interpreter: $("$PYTHON" --version 2>&1)"

"$PYTHON" -m venv "$RUNTIME_DIR/venv"
# shellcheck disable=SC1091
source "$RUNTIME_DIR/venv/bin/activate"

pip install --upgrade pip
pip install -e "$REPO_ROOT"
playwright install chromium

if [ ! -f "$RUNTIME_DIR/.env" ]; then
  cp "$REPO_ROOT/.env.example" "$RUNTIME_DIR/.env"
  echo "Created $RUNTIME_DIR/.env from template — add your ANTHROPIC_API_KEY."
fi

echo
echo "Done. Activate with:  source $RUNTIME_DIR/venv/bin/activate"
echo "Prove headless Chromium:  python $REPO_ROOT/bidplus/scripts/check_chromium.py"

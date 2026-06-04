#!/bin/zsh

set -euo pipefail

usage() {
  echo "Usage: ./run.sh <command> [args]"
  echo ""
  echo "Commands:"
  echo "  run                                Full fetch + Pass 1 + export"
  echo "  run-pass2 <excel_path>|--no-file   Ingest (optional) + Pass 2 + export"
  echo "  score-pending                      Score unscored bids only"
  echo "  export-excel                       Regenerate full Excel from DB"
  echo "  ingest-excel [path]                Ingest human edits from Excel"
}

VALID_COMMANDS=("run" "run-pass2" "score-pending" "export-excel" "ingest-excel")
CMD="${1:-}"

if [[ -z "$CMD" ]]; then
  usage
  exit 1
fi

valid=0
for c in "${VALID_COMMANDS[@]}"; do
  [[ "$CMD" == "$c" ]] && valid=1 && break
done

if [[ $valid -eq 0 ]]; then
  echo "Unknown command: $CMD"
  usage
  exit 1
fi

cd "$(dirname "$0")"

# Prefer project-local virtual environments.
if [[ -f ".venv/bin/activate" ]]; then
  source ".venv/bin/activate"
elif [[ -f "venv/bin/activate" ]]; then
  source "venv/bin/activate"
else
  echo "No virtual environment found."
  echo "Create one with:"
  echo "  python3 -m venv .venv"
  echo "  source .venv/bin/activate"
  echo "  pip install -r requirements.txt"
  exit 1
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo -n "Enter ANTHROPIC_API_KEY: "
  read -rs ANTHROPIC_API_KEY
  echo
  export ANTHROPIC_API_KEY
fi

RESOLVED_ARGS=()
for arg in "$@"; do
  if [[ -e "$arg" ]]; then
    RESOLVED_ARGS+=("$(realpath "$arg")")
  else
    RESOLVED_ARGS+=("$arg")
  fi
done

python -u isro_tool.py "${RESOLVED_ARGS[@]}"

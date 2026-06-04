#!/bin/zsh
# =============================================================================
# HAL Tool — external runner
# Run this script directly from a terminal without Claude CLI.
# =============================================================================
#
# USAGE
#   ./run_hal.sh <command> [args]
#
# COMMANDS
# ─────────────────────────────────────────────────────────────────────────────
#
# run
#   Fetch all active tenders from the HAL e-procurement portal, score them
#   with Pass 1 (Haiku), and export an updated Excel file.
#
#   Full scrape every run — all ~143 active tenders are fetched each time.
#   Re-fetched tenders already in the DB are updated safely; Pass 1 scores
#   are never overwritten on re-fetch.
#
#   Lifecycle transitions on re-fetch:
#     - Tender seen for the first time        → bid_status = NEW
#     - Tender re-fetched, closing date same  → bid_status = ACTIVE
#     - Tender re-fetched, closing date moved → bid_status = EXTENDED
#     - Closing date < today                  → bid_status = CLOSED
#
# ─────────────────────────────────────────────────────────────────────────────
#
# run-pass2 <excel_path> | --no-file
#   Score tenders eligible for Pass 2.
#
#   Candidates (evaluated in order):
#     - run_pass2 = Y  → always included, regardless of Pass 1 score
#     - pass1_score >= 3 AND run_pass2 blank → included automatically
#     - run_pass2 = N  → explicitly excluded, regardless of score
#
#   Input options (one required):
#     <excel_path>   Path to the pass1 Excel to ingest before scoring.
#                    Reads Run Pass 2 Y/N flags and human overrides,
#                    then scores all eligible candidates from DB.
#     --no-file      Skip ingest — run Pass 2 using existing DB flags only.
#
#   Workflow (with Excel):
#     1. Open the latest exports/pass1_YYYY-MM-DD.xlsx in Excel.
#     2. Review tenders — set "Run Pass 2" to Y (include) or N (exclude).
#        Leave blank to auto-include all Pass 1 score >= 3 tenders.
#     3. Optionally set Human Override Score / Human Override Reason.
#     4. Save the file.
#     5. Run: ./run_hal.sh run-pass2 exports/pass1_YYYY-MM-DD.xlsx
#
#   What happens:
#     - Ingests the Excel (or skips if --no-file).
#     - Downloads all PDFs for each candidate tender.
#     - Strips boilerplate; sends cleaned text to Sonnet.
#     - Extracts EMD amount and contract value from PDF text.
#     - Saves PDFs to downloads/<Recommendation>/<date>/<tender_number>/.
#     - Updates DB and exports pass2_YYYY-MM-DD.xlsx + bids_YYYY-MM-DD.xlsx.
#     - Tenders that fail PDF download are marked attempted and skipped on
#       future runs — no endless retries.
#
# ─────────────────────────────────────────────────────────────────────────────
#
# score-pending
#   Run Pass 1 scoring for any tenders already in the DB with no score yet.
#   Use this if a previous run fetched tenders but scoring was interrupted
#   (e.g., API spend limit hit). Does not fetch new tenders.
#
# export-excel
#   Regenerate today's full snapshot Excel from the current DB state.
#   No API calls. Safe to run at any time.
#   Human-edited columns (Run Pass 2, Human Override Score/Reason) are
#   preserved from the existing file if it already exists today.
#
# ingest-excel [path]
#   Read a specific Excel file and sync its human columns back to the DB:
#     - Human Override Score / Reason → stored and fed into few-shot examples
#     - Run Pass 2 = Y → flags the tender for Pass 2 scoring
#     - Run Pass 2 = N → blocks the tender from Pass 2
#   If no path is given, processes all unread Excel files in exports/.
#
# =============================================================================

usage() {
    echo ""
    echo "Usage: ./run_hal.sh <command> [args]"
    echo ""
    echo "Commands:"
    echo "  run                              Fetch tenders + Pass 1 score + export Excel"
    echo "  run-pass2 <excel_path>|--no-file Ingest Excel + Pass 2 PDF score + export Excel"
    echo "  score-pending                    Score unscored tenders in DB (no fetch)"
    echo "  export-excel                     Regenerate today's Excel from DB (no API calls)"
    echo "  ingest-excel [path]              Sync human edits from a specific Excel file"
    echo ""
    echo "See comments in this file for full details on each command."
    echo ""
}

VALID_COMMANDS=("run" "run-pass2" "score-pending" "export-excel" "ingest-excel")

CMD="${1:-}"

if [[ -z "$CMD" ]]; then
    echo "Error: no command specified."
    usage
    exit 1
fi

valid=0
for c in "${VALID_COMMANDS[@]}"; do
    [[ "$CMD" == "$c" ]] && valid=1 && break
done

if [[ $valid -eq 0 ]]; then
    echo "Error: unknown command '$CMD'."
    usage
    exit 1
fi

cd "$(dirname "$0")"
source venv/bin/activate

if [[ -z "$ANTHROPIC_API_KEY" ]]; then
    echo -n "Enter ANTHROPIC_API_KEY: "
    read -rs ANTHROPIC_API_KEY
    echo
    export ANTHROPIC_API_KEY
fi

# Resolve any file/directory arguments to absolute paths
RESOLVED_ARGS=()
for arg in "$@"; do
    if [[ -e "$arg" ]]; then
        RESOLVED_ARGS+=("$(realpath "$arg")")
    else
        RESOLVED_ARGS+=("$arg")
    fi
done

python -u hal_tool.py "${RESOLVED_ARGS[@]}"

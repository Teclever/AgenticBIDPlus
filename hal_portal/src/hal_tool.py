"""
HAL bid automation tool — CLI entry point.

Usage:
  python hal_tool.py run                           # Full pipeline: scrape + Pass 1 score + export
  python hal_tool.py scrape-score                  # Orchestrator: scrape + CLOSED sweep + Pass 1 (no Excel/Pass 2)
  python hal_tool.py explain <tender_no> <line_no> # Dry-run JSON: input fields -> prompt -> stored Pass-1 result
  python hal_tool.py run-pass2 <excel_path>        # Ingest Excel + Pass 2 PDF score + export
  python hal_tool.py run-pass2 --no-file           # Skip ingest, run Pass 2 using existing DB flags
  python hal_tool.py score-pending                 # Score unscored tenders in DB (no fetch)
  python hal_tool.py export-excel                  # Regenerate today's Excel from DB (no API calls)
  python hal_tool.py ingest-excel [path]           # Sync human edits from a specific Excel
"""

import datetime
import json
import sys
from pathlib import Path

from config import (
    BROWSER_PROFILE_DIR,
    CAPABILITY_REF_PATH,
    EXPORTS_DIR,
    chromium_launch_args,
)
from modules.db import (
    _get_conn,
    count_rejected_unscored,
    get_unexported_pass1_tender_numbers,
    get_unscored_tenders,
    init_db,
    mark_pass1_exported,
    query_pass2_candidates,
    sweep_closed_tenders,
    update_pass1_score,
    upsert_raw_tender,
    upsert_tender,
)
from modules.excel_export import export_pass1_delta, export_pass2_delta, export_to_excel
from modules.excel_ingest import ingest_all_pending, ingest_excel
from modules.fetcher import fetch_all_tenders
from modules.scorer_pass1 import build_pass1_prompt, score_bids_pass1_bulk
from modules.scorer_pass2 import score_tender_pass2


# ── helpers ────────────────────────────────────────────────────────────────────

def _load_capability_ref() -> str:
    path = Path(CAPABILITY_REF_PATH)
    if not path.exists():
        print(f"[error] Capability reference not found: {path}", file=sys.stderr)
        sys.exit(1)
    return path.read_text()


def _today_path(prefix: str) -> str:
    today = datetime.date.today().isoformat()
    return str(EXPORTS_DIR / f"{prefix}_{today}.xlsx")


# ── pipeline steps ─────────────────────────────────────────────────────────────

def _scrape_tenders() -> int:
    """Scrape all active tenders via headless browser. Returns total count fetched."""
    def on_page(records):
        for r in records:
            upsert_raw_tender(r)

    return fetch_all_tenders(on_page=on_page)


def _score_pending_tenders() -> tuple[int, int]:
    """Run Pass 1 scoring on all unscored tenders. Returns (scored_count, skipped_count)."""
    cap_ref  = _load_capability_ref()
    unscored = [dict(r) for r in get_unscored_tenders()]
    skipped  = count_rejected_unscored()
    total    = len(unscored)

    if not total:
        print("  No unscored tenders.")
        return 0, skipped

    print(f"  Scoring {total} unscored tender(s) ({skipped} rejected/closed skipped)…")

    def save_batch(scored_chunk):
        for item in scored_chunk:
            fields = {
                "pass1_score":          item.get("score"),
                "pass1_confidence":     item.get("confidence"),
                "pass1_domain":         item.get("domain"),
                "pass1_rationale":      item.get("rationale"),
                "pass1_gaps":           item.get("gaps"),
                "pass1_recommendation": item.get("recommendation"),
                "pass1_matching_tech":  item.get("matching_tech"),
            }
            update_pass1_score(item["tender_number"], item["line_number"], fields)

    score_bids_pass1_bulk(unscored, cap_ref, on_batch=save_batch)
    print(f"  Scoring complete: {total} tender(s).")
    return total, skipped


def _run_pass2_pipeline() -> list[dict]:
    """Score all Pass 2 candidates. Returns list of result dicts for scored tenders.

    One Playwright context and one portal search page are shared across the
    entire run.  The search page is reused between tenders (navigated back to
    the search form URL) so the portal session stays warm and we never need to
    re-crawl the Mobility SPA iframe for each individual tender.
    """
    from playwright.sync_api import sync_playwright
    from modules.session import open_free_view, find_results_scope

    cap_ref    = _load_capability_ref()
    candidates = [dict(r) for r in query_pass2_candidates()]
    print(f"  Pass 2: {len(candidates)} tender(s) flagged for PDF scoring.")

    if not candidates:
        return []

    scored: list[dict] = []

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE_DIR),
            headless=True,
            accept_downloads=True,
            ignore_https_errors=True,
            args=chromium_launch_args(),
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()

            # ── Navigate to the portal once and obtain the search page ──────────
            print("  [pass2] Opening HAL portal search…")
            open_free_view(context, page)
            search_page = find_results_scope(context)
            if search_page is None:
                print("  [pass2] ERROR — could not reach portal search form. Aborting.")
                return []
            # Capture the URL now (before any per-tender POST) so we can
            # reload back to the empty search form between tenders.
            search_url = search_page.url
            print(f"  [pass2] Search page ready: {search_url[:70]}")

            for tender in candidates:
                tn   = tender["tender_number"]
                ln   = tender["line_number"]
                desc = str(tender.get("tender_description") or "")[:60]
                print(f"  Scoring: ({tn}, {ln}) — {desc}")
                try:
                    result = score_tender_pass2(
                        dict(tender), cap_ref, context, search_page, search_url
                    )
                except Exception as e:
                    print(f"  [error] ({tn}, {ln}): {e}")
                    continue

                if result is None:
                    print(f"  [skip] ({tn}, {ln}): scoring returned None (marked attempted)")
                    continue

                result["tender_number"] = tn
                result["line_number"]   = ln
                upsert_tender(result)

                if result.get("pass2_score") is not None:
                    scored.append(result)
        finally:
            context.close()

    return scored


# ── commands ───────────────────────────────────────────────────────────────────

def cmd_run() -> None:
    """Full pipeline: pending ingest → full scrape → CLOSED sweep → Pass 1 → export."""
    print("=== Phase 0: Ingesting pending Excels ===")
    ingest_all_pending()

    print("\n=== Phase 1: Scraping HAL portal ===")
    total = _scrape_tenders()
    print(f"  {total} tender(s) fetched and stored.")

    print("\n=== Phase 2: CLOSED sweep ===")
    closed_count = sweep_closed_tenders()
    print(f"  {closed_count} tender(s) transitioned to CLOSED.")

    print("\n=== Phase 3: Pass 1 scoring ===")
    scored_count, skipped = _score_pending_tenders()
    print(f"  Skipped (rejected/closed): {skipped}")

    print("\n=== Phase 4: Export ===")
    # Delta = all tenders scored but not yet exported (this run + any previously crashed runs)
    delta_tenders = get_unexported_pass1_tender_numbers()
    export_pass1_delta(delta_tenders, _today_path("pass1"))
    mark_pass1_exported([(t["tender_number"], t["line_number"]) for t in delta_tenders])
    export_to_excel(_today_path("bids"))

    today = datetime.date.today().isoformat()
    print(f"\nDone.")
    print(f"  Pass 1 delta : exports/pass1_{today}.xlsx  ({len(delta_tenders)} tender(s))")
    print(f"  Full snapshot: exports/bids_{today}.xlsx")


def cmd_scrape_score() -> None:
    """Orchestrator pipeline: scrape -> CLOSED sweep -> Pass 1. No Excel ingest/export, no Pass 2.

    This is the entry point the bidplus PortalAdapter shells out to. Pass 2 is
    intentionally absent — it is replaced by the S5 Sonnet summarization module.
    """
    print("=== Phase 1: Scraping HAL portal ===")
    total = _scrape_tenders()
    print(f"  {total} tender(s) fetched and stored.")

    print("\n=== Phase 2: CLOSED sweep ===")
    closed_count = sweep_closed_tenders()
    print(f"  {closed_count} tender(s) transitioned to CLOSED.")

    print("\n=== Phase 3: Pass 1 scoring ===")
    scored_count, skipped = _score_pending_tenders()
    print(f"  Skipped (rejected/closed): {skipped}")

    print("\nDone (scrape-score).")


def cmd_explain(tn: str | None, ln: str | None) -> None:
    """Print a single JSON dry-run object for one tender (NO API call).

    Reads the stored row from the DB, assembles the deterministic Pass-1 prompt
    via build_pass1_prompt([row]), and reports the stored pass1_* result. Only the
    JSON object is printed to stdout (so the adapter can parse it); human/log lines
    go to stderr.
    """
    if not tn or not ln:
        print("Error: explain requires <tender_number> <line_number>.", file=sys.stderr)
        sys.exit(1)

    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM tenders WHERE tender_number=? AND line_number=?",
            (tn, ln),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        print(f"Error: no tender found for {tn} | {ln}", file=sys.stderr)
        sys.exit(1)

    row_dict = dict(row)

    # The listing fields build_pass1_prompt actually consumes.
    input_field_names = [
        "tender_number", "line_number", "tender_description", "buyer",
        "tender_region", "estimated_cost", "emd_listing", "closing_date", "bidder_type",
    ]
    input_fields = {f: row_dict.get(f) for f in input_field_names}

    assembled_prompt = build_pass1_prompt([row_dict])

    parsed_result = {
        "score":          row_dict.get("pass1_score"),
        "confidence":     row_dict.get("pass1_confidence"),
        "domain":         row_dict.get("pass1_domain"),
        "matching_tech":  row_dict.get("pass1_matching_tech"),
        "gaps":           row_dict.get("pass1_gaps"),
        "rationale":      row_dict.get("pass1_rationale"),
        "recommendation": row_dict.get("pass1_recommendation"),
    }

    payload = {
        "portal": "hal",
        "source_pk": f"{tn}|{ln}",
        "input_fields": input_fields,
        "assembled_prompt": assembled_prompt,
        "parsed_result": parsed_result,
    }

    print(json.dumps(payload, ensure_ascii=False))


def cmd_run_pass2(arg: str | None) -> None:
    """Ingest Excel (or skip) → Pass 2 PDF scoring → export."""
    if arg is None:
        print("Error: run-pass2 requires an argument.", file=sys.stderr)
        print("  python hal_tool.py run-pass2 <excel_path>   # ingest + score", file=sys.stderr)
        print("  python hal_tool.py run-pass2 --no-file      # skip ingest, use DB flags", file=sys.stderr)
        sys.exit(1)

    if arg == "--no-file":
        print("=== Phase 0: Skipping ingest (--no-file) ===")
    else:
        excel_path = Path(arg)
        if not excel_path.exists():
            print(f"Error: file not found: {excel_path}", file=sys.stderr)
            sys.exit(1)
        print(f"=== Phase 0: Ingesting {excel_path.name} ===")
        ingest_excel(str(excel_path), force=True)

    print("\n=== Phase 1: Pass 2 scoring ===")
    scored = _run_pass2_pipeline()

    print("\n=== Phase 2: Export ===")
    export_pass2_delta(scored, _today_path("pass2"))
    export_to_excel(_today_path("bids"))

    today = datetime.date.today().isoformat()
    print(f"\nDone.")
    print(f"  Pass 2 delta : exports/pass2_{today}.xlsx  ({len(scored)} tender(s) scored)")
    print(f"  Full snapshot: exports/bids_{today}.xlsx")


def cmd_score_pending() -> None:
    """Score unscored tenders in DB without fetching. Useful after an interrupted run."""
    print("=== Scoring pending tenders (no fetch) ===")
    scored_count, skipped = _score_pending_tenders()

    print("\n=== Export ===")
    delta_tenders = get_unexported_pass1_tender_numbers()
    export_pass1_delta(delta_tenders, _today_path("pass1"))
    mark_pass1_exported([(t["tender_number"], t["line_number"]) for t in delta_tenders])
    export_to_excel(_today_path("bids"))

    today = datetime.date.today().isoformat()
    print(f"\nDone.")
    print(f"  Pass 1 delta : exports/pass1_{today}.xlsx  ({len(delta_tenders)} tender(s))")
    print(f"  Full snapshot: exports/bids_{today}.xlsx")
    print(f"  Skipped (rejected/closed): {skipped}")


def cmd_export_excel() -> None:
    """Regenerate today's full-snapshot Excel from DB. No API calls."""
    export_to_excel(_today_path("bids"))
    today = datetime.date.today().isoformat()
    print(f"Exported: exports/bids_{today}.xlsx")


def cmd_ingest_excel(path: str | None) -> None:
    """Sync human edits from a specific Excel file, or all pending files."""
    if path:
        ingest_excel(path, force=True)
    else:
        ingest_all_pending()


# ── entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    init_db()

    cmd = sys.argv[1] if len(sys.argv) > 1 else ""

    if cmd == "run":
        cmd_run()

    elif cmd == "scrape-score":
        cmd_scrape_score()

    elif cmd == "explain":
        tn = sys.argv[2] if len(sys.argv) > 2 else None
        ln = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_explain(tn, ln)

    elif cmd == "run-pass2":
        arg = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_run_pass2(arg)

    elif cmd == "score-pending":
        cmd_score_pending()

    elif cmd == "export-excel":
        cmd_export_excel()

    elif cmd == "ingest-excel":
        path = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_ingest_excel(path)

    else:
        if cmd:
            print(f"Unknown command: {cmd!r}", file=sys.stderr)
        print(__doc__)
        sys.exit(1 if cmd else 0)


if __name__ == "__main__":
    main()

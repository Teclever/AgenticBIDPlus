"""
ISRO bid automation tool.

Usage:
  python isro_tool.py run
  python isro_tool.py run-pass2 <excel_path>
  python isro_tool.py run-pass2 --no-file
  python isro_tool.py score-pending
  python isro_tool.py export-excel
  python isro_tool.py ingest-excel [path]
"""

from __future__ import annotations

import datetime
import os
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    def load_dotenv() -> None:
        return None

from config import CAPABILITY_REF_PATH, EXPORTS_DIR, PASS2_THRESHOLD, ensure_runtime_dirs
from modules.db import (
    get_all_bids,
    get_unexported_pass1_bids,
    get_unscored_bids,
    init_db,
    mark_pass1_exported,
    query_pass2_candidates,
    sweep_closed_bids,
    update_pass1_score,
    update_pass2_score,
    upsert_raw_bid,
)
from modules.excel_export import export_pass1_delta, export_pass2_delta, export_to_excel
from modules.excel_ingest import ingest_all_pending, ingest_excel
from modules.fetcher import fetch_all_tenders
from modules.logutil import log_banner, log_done, log_info, log_ok, log_phase, log_step, log_warn
from modules.scorer_pass1 import score_bids_pass1_bulk
from modules.scorer_pass2 import score_bid_pass2


def _today_path(prefix: str) -> str:
    return str(EXPORTS_DIR / f"{prefix}_{datetime.date.today().isoformat()}.xlsx")


def _load_capability_ref() -> str:
    p = Path(CAPABILITY_REF_PATH)
    if not p.exists():
        log_warn(f"Capability reference missing at {p}; using built-in fallback.")
        return (
            "Teclever is strong in software engineering, testing, simulation, automation, "
            "embedded systems, mission software, and aerospace engineering support."
        )
    log_step(f"Loaded capability reference: {p.name}")
    return p.read_text(encoding="utf-8")


def _check_api_key() -> None:
    if os.getenv("ANTHROPIC_API_KEY", "").strip():
        log_ok("ANTHROPIC_API_KEY is set.")
    else:
        log_warn("ANTHROPIC_API_KEY is not set — scoring phases will fail.")


def cmd_run() -> None:
    log_banner("run (daily pipeline)")
    _check_api_key()
    t0 = time.time()

    log_phase(0, "Skip Excel ingest (DB remains source of truth)")
    log_info("No automatic Excel ingest in daily run. Use `ingest-excel` explicitly if needed.")

    log_phase(1, "Scrape ISRO portal")
    bids: list[dict] = []
    inserted = 0
    updated = 0
    try:
        bids = fetch_all_tenders()
        log_info(f"Upserting {len(bids)} tender(s) into database…")
        for i, bid in enumerate(bids, start=1):
            op = upsert_raw_bid(bid)
            if op == "inserted":
                inserted += 1
            else:
                updated += 1
            if i % 25 == 0 or i == len(bids):
                log_step(f"stored {i}/{len(bids)} (new={inserted}, updated={updated})")
        log_ok(
            f"Scrape complete: fetched={len(bids)} -> inserted={inserted}, updated={updated}"
        )
    except Exception as exc:
        log_warn(f"Scrape failed or skipped: {exc}")

    log_phase(2, "CLOSED sweep")
    closed = sweep_closed_bids()
    log_ok(f"{closed} tender(s) marked CLOSED.")

    log_phase(3, "Pass 1 scoring (Anthropic)")
    scored = _run_pass1()

    log_phase(4, "Export Excel")
    pass1_n, bids_path, pass1_path = _export_pass1_and_full()

    elapsed = int(time.time() - t0)
    log_done(
        f"Fetched {len(bids)} (inserted={inserted}, updated={updated}) | Pass1 scored this run: {scored} | "
        f"pass1 export: {pass1_n} rows | full: {bids_path} | elapsed {elapsed}s"
    )


def cmd_run_pass2(arg: str | None) -> None:
    if arg is None:
        print("Error: run-pass2 requires <excel_path> or --no-file", file=sys.stderr)
        sys.exit(1)

    log_banner("run-pass2")
    _check_api_key()
    t0 = time.time()

    log_phase(0, "Ingest human review from Excel")
    if arg == "--no-file":
        log_info("Skipping ingest (--no-file); using existing DB flags.")
    else:
        xlsx = Path(arg)
        if not xlsx.exists():
            print(f"Error: file not found: {xlsx}", file=sys.stderr)
            sys.exit(1)
        found, applied = ingest_excel(str(xlsx), force=True)
        log_ok(f"Ingested {xlsx.name}: overrides found={found}, applied={applied}")

    log_phase(1, f"Pass 2 scoring (auto threshold >= {PASS2_THRESHOLD})")
    cap_ref = _load_capability_ref()
    candidates = [dict(x) for x in query_pass2_candidates()]
    total = len(candidates)
    log_info(f"{total} candidate(s) selected for Pass 2.")
    if total == 0:
        log_info("Nothing to score. Check Run Pass 2 flags and Pass 1 scores.")
    scored_rows: list[dict] = []
    skipped = 0
    for i, bid in enumerate(candidates, start=1):
        tid = bid["tender_id"]
        desc = str(bid.get("tender_description") or "")[:55]
        log_step(f"[{i}/{total}] {tid} — {desc}")
        result = score_bid_pass2(bid, cap_ref)
        if not result:
            skipped += 1
            log_warn(f"[{i}/{total}] {tid} — no score (download/parse/API issue)")
            continue
        update_pass2_score(tid, result)
        merged = dict(bid)
        merged.update(result)
        scored_rows.append(merged)
        rec = result.get("pass2_recommendation", "")
        score = result.get("pass2_score", "")
        log_ok(f"[{i}/{total}] {tid} — score={score} recommendation={rec}")

    log_phase(2, "Export Excel")
    pass2_path = _today_path("pass2")
    bids_path = _today_path("bids")
    export_pass2_delta(scored_rows, pass2_path)
    log_ok(f"Pass2 delta written: {pass2_path} ({len(scored_rows)} row(s))")
    export_to_excel([dict(x) for x in get_all_bids()], bids_path)
    log_ok(f"Full snapshot written: {bids_path}")

    elapsed = int(time.time() - t0)
    log_done(
        f"Pass2 scored={len(scored_rows)} skipped={skipped} candidates={total} | elapsed {elapsed}s"
    )


def cmd_score_pending() -> None:
    log_banner("score-pending")
    _check_api_key()
    log_phase(1, "Pass 1 scoring (unscored only)")
    scored = _run_pass1()
    log_phase(2, "Export Excel")
    pass1_n, bids_path, pass1_path = _export_pass1_and_full()
    log_done(f"Pass1 scored={scored} | pass1 delta={pass1_n} | full={bids_path}")


def cmd_export_excel() -> None:
    log_banner("export-excel")
    rows = [dict(x) for x in get_all_bids()]
    path = _today_path("bids")
    log_info(f"Exporting {len(rows)} row(s) from database…")
    export_to_excel(rows, path)
    log_done(f"Written: {path}")


def cmd_ingest_excel(path: str | None) -> None:
    log_banner("ingest-excel")
    if path:
        found, applied = ingest_excel(path, force=True)
        log_done(f"{Path(path).name}: found={found}, applied={applied}")
    else:
        ingest_all_pending()
        log_done("Pending Excel files processed.")


def _run_pass1() -> int:
    all_rows = [dict(x) for x in get_all_bids()]
    rows = [dict(x) for x in get_unscored_bids()]
    total_seen = len(all_rows)
    ignored_scored = sum(1 for x in all_rows if x.get("pass1_score") is not None)
    ignored_closed = sum(1 for x in all_rows if x.get("bid_status") == "CLOSED")
    ignored_total = max(0, total_seen - len(rows))
    log_info(
        f"Pass1 queue: to_score={len(rows)}, ignored={ignored_total} "
        f"(already_scored={ignored_scored}, closed={ignored_closed})"
    )
    if not rows:
        log_info("No unscored active tenders — skipping LLM calls.")
        return 0
    cap_ref = _load_capability_ref()
    scored_count = 0

    def save_batch(batch: list[dict]) -> None:
        nonlocal scored_count
        for item in batch:
            update_pass1_score(item["tender_id"], item)
            if item.get("pass1_score") is not None:
                scored_count += 1

    try:
        score_bids_pass1_bulk(rows, cap_ref, on_batch=save_batch)
        log_ok(f"Pass 1 complete: {scored_count}/{len(rows)} received scores.")
    except Exception as exc:
        log_warn(f"Pass 1 scoring error: {exc}")
    return scored_count


def _export_pass1_and_full() -> tuple[int, str, str]:
    delta = [dict(x) for x in get_unexported_pass1_bids()]
    pass1_path = _today_path("pass1")
    bids_path = _today_path("bids")
    if delta:
        log_info(f"Writing Pass1 delta ({len(delta)} row(s)) → {pass1_path}")
        export_pass1_delta(delta, pass1_path)
        mark_pass1_exported([x["tender_id"] for x in delta])
    else:
        log_info("No new Pass1 rows for delta export.")
    all_rows = [dict(x) for x in get_all_bids()]
    log_info(f"Writing full snapshot ({len(all_rows)} row(s)) → {bids_path}")
    export_to_excel(all_rows, bids_path)
    return len(delta), bids_path, pass1_path


def main() -> None:
    load_dotenv()
    ensure_runtime_dirs()
    init_db()
    log_step(f"Database ready: data/bids.db")

    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    arg = sys.argv[2] if len(sys.argv) > 2 else None

    if cmd == "run":
        cmd_run()
    elif cmd == "run-pass2":
        cmd_run_pass2(arg)
    elif cmd == "score-pending":
        cmd_score_pending()
    elif cmd == "export-excel":
        cmd_export_excel()
    elif cmd == "ingest-excel":
        cmd_ingest_excel(arg)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

"""
HAL corporate-tenders bid automation tool (portal key: ``halc``).

Targets the HAL corporate tenders site (https://hal-india.co.in/tender), served by
a WordPress REST backend. Distinct from the ``hal`` e-procurement portal.

Usage:
  python halc_tool.py run
  python halc_tool.py scrape-score                 # Orchestrator: scrape + CLOSED sweep + detail enrich (no Pass 1 / Excel)
  python halc_tool.py explain <tender_id>          # Dry-run JSON: input fields -> prompt -> stored Pass-1 result
  python halc_tool.py fetch-docs <tender_id> --out <dir>
  python halc_tool.py run-pass2 <excel_path>
  python halc_tool.py run-pass2 --no-file
  python halc_tool.py score-pending
  python halc_tool.py export-excel
  python halc_tool.py ingest-excel [path]
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    def load_dotenv() -> None:
        return None

from config import (
    CAPABILITY_REF_PATH,
    EXPORTS_DIR,
    PASS1_DETAIL_CHARS,
    PASS2_THRESHOLD,
    ensure_runtime_dirs,
)
from modules.db import (
    _conn,
    get_all_bids,
    get_unexported_pass1_bids,
    get_unscored_bids,
    init_db,
    mark_pass1_exported,
    query_pass2_candidates,
    sweep_closed_bids,
    update_detail_text,
    update_pass1_score,
    update_pass2_score,
    upsert_raw_bid,
)
from modules.excel_export import export_pass1_delta, export_pass2_delta, export_to_excel
from modules.excel_ingest import ingest_all_pending, ingest_excel
from modules.fetcher import collect_doc_links, fetch_detail_text, fetch_listing, make_session
from modules.logutil import log_banner, log_done, log_info, log_ok, log_phase, log_step, log_warn
from modules.scorer_pass1 import build_pass1_prompt, score_bids_pass1_bulk
from modules.scorer_pass2 import _safe_name, _suffix, score_bid_pass2


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

    log_phase(1, "Scrape HAL tenders site")
    bids: list[dict] = []
    inserted = updated = 0
    try:
        bids = fetch_listing()
        log_info(f"Upserting {len(bids)} tender(s) into database…")
        for i, bid in enumerate(bids, start=1):
            op = upsert_raw_bid(bid)
            inserted += op == "inserted"
            updated += op != "inserted"
            if i % 25 == 0 or i == len(bids):
                log_step(f"stored {i}/{len(bids)} (new={inserted}, updated={updated})")
        log_ok(f"Scrape complete: fetched={len(bids)} -> inserted={inserted}, updated={updated}")
    except Exception as exc:
        log_warn(f"Scrape failed or skipped: {exc}")

    log_phase(2, "CLOSED sweep")
    closed = sweep_closed_bids()
    log_ok(f"{closed} tender(s) marked CLOSED.")

    log_phase(3, "Enrich detail text (unscored tenders only)")
    _enrich_unscored_detail_text()

    log_phase(4, "Pass 1 scoring (Anthropic)")
    scored = _run_pass1()

    log_phase(5, "Export Excel")
    pass1_n, bids_path, _ = _export_pass1_and_full()

    elapsed = int(time.time() - t0)
    log_done(
        f"Fetched {len(bids)} (inserted={inserted}, updated={updated}) | Pass1 scored this run: {scored} | "
        f"pass1 export: {pass1_n} rows | full: {bids_path} | elapsed {elapsed}s"
    )


def cmd_scrape_score() -> None:
    """Orchestrator pipeline: scrape -> CLOSED sweep -> detail enrich. NO Pass 1 / Excel.

    This is the entry point the bidplus PortalAdapter shells out to. Pass 1 is
    centralized in bidplus.scoring (two-pass eliminator + Haiku, S5), run by the
    orchestrator after the merge. Detail text is enriched here so summaries/explain
    have richer context.
    """
    log_banner("scrape-score (orchestrator)")
    _check_api_key()
    t0 = time.time()

    log_phase(1, "Scrape HAL tenders site")
    inserted = updated = 0
    try:
        bids = fetch_listing()
        log_info(f"Upserting {len(bids)} tender(s) into database…")
        for i, bid in enumerate(bids, start=1):
            op = upsert_raw_bid(bid)
            inserted += op == "inserted"
            updated += op != "inserted"
            if i % 25 == 0 or i == len(bids):
                log_step(f"stored {i}/{len(bids)} (new={inserted}, updated={updated})")
        log_ok(f"Scrape complete: fetched={len(bids)} -> inserted={inserted}, updated={updated}")
    except Exception as exc:
        log_warn(f"Scrape failed or skipped: {exc}")

    log_phase(2, "CLOSED sweep")
    closed = sweep_closed_bids()
    log_ok(f"{closed} tender(s) marked CLOSED.")

    log_phase(3, "Enrich detail text (unscored tenders only)")
    enriched = _enrich_unscored_detail_text()

    elapsed = int(time.time() - t0)
    log_done(
        f"scrape-score (scrape-only): inserted={inserted}, updated={updated}, closed={closed}, "
        f"detail_enriched={enriched} | elapsed {elapsed}s | Pass-1 centralized in bidplus.scoring"
    )


def cmd_explain(tender_id: str | None) -> None:
    """Print a single JSON dry-run object for one tender (NO API call).

    Only the JSON object is printed to stdout (so the adapter can parse it); human/
    log lines go to stderr.
    """
    if not tender_id:
        print("Error: explain requires <tender_id>.", file=sys.stderr)
        sys.exit(1)

    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM bids WHERE tender_id=?", (tender_id,)).fetchone()
    finally:
        conn.close()

    if row is None:
        print(f"Error: no tender found for {tender_id}", file=sys.stderr)
        sys.exit(1)

    row_dict = dict(row)
    input_field_names = [
        "tender_id", "ref_no", "category", "center_name", "tender_description",
        "detail_text", "bid_closing_date", "bid_opening_date",
    ]
    input_fields = {f: row_dict.get(f) for f in input_field_names}

    # Read the rubric directly (NOT via _load_capability_ref, which logs to stdout
    # and would corrupt the pure-JSON stdout the adapter parses).
    cap_path = Path(CAPABILITY_REF_PATH)
    cap_ref = cap_path.read_text(encoding="utf-8") if cap_path.exists() else ""
    assembled_prompt = build_pass1_prompt([row_dict], cap_ref, PASS1_DETAIL_CHARS)

    parsed_result = {
        "score":      row_dict.get("pass1_score"),
        "confidence": row_dict.get("pass1_confidence"),
        "domain":     row_dict.get("pass1_domain"),
        "gaps":       row_dict.get("pass1_gaps"),
        "rationale":  row_dict.get("pass1_rationale"),
    }

    payload = {
        "portal": "halc",
        "source_pk": tender_id,
        "input_fields": input_fields,
        "assembled_prompt": assembled_prompt,
        "parsed_result": parsed_result,
    }
    print(json.dumps(payload, ensure_ascii=False))


def cmd_fetch_docs(tender_id: str | None, out_dir: str | None) -> None:
    """Orchestrator doc-fetch (S6 Channel 1): download the tender's tendorfile*/Corrigendum*
    PDFs into <out_dir>. Raw files only; extraction is the §8b module's job."""
    if not tender_id or not out_dir:
        print("Error: fetch-docs requires <tender_id> --out <dir>.", file=sys.stderr)
        sys.exit(1)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    session = make_session()
    try:
        links = collect_doc_links(session, {"tender_id": tender_id})
        saved = 0
        for i, url in enumerate(links, start=1):
            try:
                resp = session.get(url, timeout=60)
                resp.raise_for_status()
                content = resp.content
            except Exception as e:
                print(f"[fetch-docs] halc link {i} failed: {e}")
                continue
            head = content[:64].lstrip().lower()
            if content[:4] == b"%PDF":
                ext = ".pdf"
            elif head.startswith(b"<!doctype") or head.startswith(b"<html"):
                print(f"[fetch-docs] halc link {i} is HTML (not a document) — skipped")
                continue
            else:
                ext = _suffix(url)
            (out / f"{_safe_name(tender_id)}_{i}{ext}").write_bytes(content)
            saved += 1
        print(f"[fetch-docs] halc {tender_id}: saved {saved} doc(s) from {len(links)} link(s) → {out}")
    finally:
        session.close()


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
        log_ok(f"[{i}/{total}] {tid} — score={result.get('pass2_score')} "
               f"recommendation={result.get('pass2_recommendation')}")

    log_phase(2, "Export Excel")
    export_pass2_delta(scored_rows, _today_path("pass2"))
    export_to_excel([dict(x) for x in get_all_bids()], _today_path("bids"))

    elapsed = int(time.time() - t0)
    log_done(f"Pass2 scored={len(scored_rows)} skipped={skipped} candidates={total} | elapsed {elapsed}s")


def cmd_score_pending() -> None:
    log_banner("score-pending")
    _check_api_key()
    log_phase(1, "Enrich detail text (unscored tenders only)")
    _enrich_unscored_detail_text()
    log_phase(2, "Pass 1 scoring (unscored only)")
    scored = _run_pass1()
    log_phase(3, "Export Excel")
    pass1_n, bids_path, _ = _export_pass1_and_full()
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


def _enrich_unscored_detail_text() -> int:
    """Fetch detail-page text only for unscored, non-CLOSED tenders that lack it."""
    rows = [dict(x) for x in get_unscored_bids()]
    pending = [r for r in rows if not str(r.get("detail_text") or "").strip()]
    log_info(f"Detail enrichment: {len(pending)} of {len(rows)} unscored tender(s) need detail text.")
    if not pending:
        log_info("All unscored tenders already have detail text — skipping fetch.")
        return 0
    session = make_session()
    fetched = 0
    try:
        for i, r in enumerate(pending, start=1):
            text = fetch_detail_text(session, r.get("tender_id"))
            if text:
                update_detail_text(r["tender_id"], text)
                fetched += 1
            if i % 25 == 0 or i == len(pending):
                log_step(f"enriched {i}/{len(pending)} (text fetched={fetched})")
    finally:
        session.close()
    log_ok(f"Detail enrichment complete: {fetched}/{len(pending)} tender(s) fetched.")
    return fetched


def _run_pass1() -> int:
    all_rows = [dict(x) for x in get_all_bids()]
    rows = [dict(x) for x in get_unscored_bids()]
    ignored_scored = sum(1 for x in all_rows if x.get("pass1_score") is not None)
    ignored_closed = sum(1 for x in all_rows if x.get("bid_status") == "CLOSED")
    log_info(
        f"Pass1 queue: to_score={len(rows)}, ignored={max(0, len(all_rows) - len(rows))} "
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


def _parse_out(argv: list[str]) -> tuple[list[str], str | None]:
    """Split '<pk...> --out <dir>' into (positional_args, out_dir)."""
    if "--out" in argv:
        i = argv.index("--out")
        return argv[:i], (argv[i + 1] if i + 1 < len(argv) else None)
    return argv, None


def main() -> None:
    load_dotenv()
    ensure_runtime_dirs()
    init_db()
    # Status line to stderr so the `explain` command keeps stdout pure JSON.
    print("    Database ready: bids.db", file=sys.stderr, flush=True)

    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    arg = sys.argv[2] if len(sys.argv) > 2 else None

    if cmd == "run":
        cmd_run()
    elif cmd == "scrape-score":
        cmd_scrape_score()
    elif cmd == "explain":
        cmd_explain(arg)
    elif cmd == "fetch-docs":
        pos, out_dir = _parse_out(sys.argv[2:])
        cmd_fetch_docs(pos[0] if pos else None, out_dir)
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

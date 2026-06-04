"""
Usage:
  python gem_tool.py run                           # Full pipeline: fetch + refresh + score + export
  python gem_tool.py run-pass2 <excel_path>        # Ingest specific Excel + Pass 2 PDF score + export Excel
  python gem_tool.py run-pass2 --no-file           # Skip ingest, run Pass 2 using existing DB flags
  python gem_tool.py score-pending                 # Score unscored bids already in DB (no fetch)
  python gem_tool.py ingest-excel [path]           # Sync human edits from a specific Excel
  python gem_tool.py export-excel                  # Regenerate today's Excel from SQLite
  python gem_tool.py show-rules                    # Print current exclusion rules
"""

import sys, json, datetime
from pathlib import Path
from modules.excel_ingest import ingest_all_pending, ingest_excel
from modules.fetcher import fetch_all_bids_for_org
from modules.scorer_pass1 import score_bid_pass1, score_bids_pass1_bulk
from modules.scorer_pass2 import score_bid_pass2
from modules.db import (upsert_bid, upsert_raw_bid, get_unscored_bids,
                         update_pass1_score, query_pass2_candidates, init_db,
                         sweep_closed_bids, count_rejected_unscored,
                         get_unexported_pass1_bid_numbers, mark_pass1_exported)
from modules.excel_export import export_to_excel, export_pass1_delta, export_pass2_delta
from modules.feedback import seed_exclusion_rules
from config import TARGET_ORGS, DB_PATH, STATE_PATH, EXPORTS_DIR, CAPABILITY_REF_PATH


def load_state() -> dict:
    if Path(STATE_PATH).exists():
        return json.loads(Path(STATE_PATH).read_text())
    return {}


def save_state(state: dict):
    Path(STATE_PATH).write_text(json.dumps(state, indent=2))


def load_capability_ref() -> str:
    return Path(CAPABILITY_REF_PATH).read_text()


def fetch_all_orgs(skip_orgs: set[str] | None = None,
                   on_org_complete=None) -> tuple[int, list[str]]:
    """
    Full fetch — no date filtering. Fetches ALL active bids for every org.
    Upserts page-by-page; extension detection happens inside upsert_raw_bid.
    Calls on_org_complete after each org for crash-recovery checkpointing.
    Returns (total_bids_stored, extended_bid_numbers).
    """
    total                = 0
    total_new            = 0
    total_updated        = 0
    total_pages          = 0
    extended_bid_numbers = []

    for ministry, orgs in TARGET_ORGS.items():
        for org in orgs:
            if skip_orgs and org in skip_orgs:
                print(f"  [skip] {org} — already fetched this run")
                continue

            print(f"  Fetching: {org} ({ministry})")

            org_extended = []
            org_counts   = {"new": 0, "updated": 0}

            def handle_page(bids, _ext=org_extended, _c=org_counts):
                for b in bids:
                    result = upsert_raw_bid(b)
                    if result.get("is_new"):
                        _c["new"] += 1
                    else:
                        _c["updated"] += 1
                    if result.get("is_extended"):
                        _ext.append(b["bid_number"])

            try:
                count, metrics = fetch_all_bids_for_org(
                    ministry, org, on_page=handle_page
                )
            except Exception as e:
                print(f"  [error] {org}: {e}")
                continue

            total         += count
            total_new     += org_counts["new"]
            total_updated += org_counts["updated"]
            total_pages   += metrics["pages_scanned"]
            num_found      = metrics.get("num_found", 0)

            coverage_warn = ""
            if num_found and count < num_found:
                coverage_warn = f"  ⚠ portal reported {num_found}, fetched {count}"

            print(f"    {count} fetched → {org_counts['new']} new, "
                  f"{org_counts['updated']} updated  "
                  f"({metrics['pages_scanned']} pages){coverage_warn}")
            if org_extended:
                print(f"    {len(org_extended)} extension(s) detected")
            extended_bid_numbers.extend(org_extended)

            if on_org_complete:
                on_org_complete(org)

    print(f"\nFetch complete: {total} fetched → "
          f"{total_new} new rows inserted, {total_updated} existing rows updated "
          f"across {total_pages} pages.")
    return total, extended_bid_numbers



def score_pending_bids() -> tuple[list[str], int]:
    """
    Score eligible unscored bids (excludes rejected, declined, and CLOSED).
    Returns (scored_bid_numbers, skipped_count).
    """
    cap_ref  = load_capability_ref()
    unscored = get_unscored_bids()
    skipped  = count_rejected_unscored()
    delta_bid_numbers = [b["bid_number"] for b in unscored]
    total = len(unscored)
    print(f"Scoring {total} unscored bids "
          f"({skipped} rejected/closed skipped)...")

    def save_batch(scored_chunk):
        for bid in scored_chunk:
            update_pass1_score(bid["bid_number"], bid)

    score_bids_pass1_bulk(unscored, cap_ref, on_batch=save_batch)
    print(f"Scoring complete: {total} bids.")
    return delta_bid_numbers, skipped


def run_pipeline2() -> list[str]:
    """
    Run Pass 2 scoring on all eligible candidates.
    Returns list of bid_numbers successfully scored in this run.
    """
    cap_ref    = load_capability_ref()
    candidates = query_pass2_candidates()
    print(f"Pass 2: {len(candidates)} bids flagged for PDF scoring.")

    scored_bid_numbers = []
    for bid in candidates:
        print(f"  Scoring: {bid['bid_number']} — {str(bid.get('items', ''))[:60]}")
        try:
            bid = score_bid_pass2(bid, cap_ref)
            upsert_bid(bid)
            if bid.get("pass2_score") is not None:
                scored_bid_numbers.append(bid["bid_number"])
        except Exception as e:
            print(f"  [error] {bid['bid_number']}: {e}")

    today = datetime.date.today().isoformat()
    export_pass2_delta(scored_bid_numbers, f"{EXPORTS_DIR}/pass2_{today}.xlsx")
    export_to_excel(f"{EXPORTS_DIR}/bids_{today}.xlsx")
    print("Pipeline 2 complete. Excel regenerated.")
    return scored_bid_numbers


def main():
    init_db()
    seed_exclusion_rules()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"

    if cmd == "run":
        state = load_state()

        print("=== Phase 0: Ingesting pending Excels ===")
        ingest_all_pending()

        # Crash recovery: resume from last completed org if a previous run was interrupted
        completed = set(state.get("completed_orgs", []))
        if completed:
            print(f"\n=== Phase 1: Resuming interrupted fetch "
                  f"({len(completed)} orgs already done) ===")
        else:
            print("\n=== Phase 1: Full fetch — all active bids ===")
            state["completed_orgs"] = []
            save_state(state)

        def mark_org_complete(org):
            completed.add(org)
            state["completed_orgs"] = list(completed)
            save_state(state)

        total_fetched, extended_bid_numbers = fetch_all_orgs(
            skip_orgs=completed, on_org_complete=mark_org_complete
        )

        state["last_run"] = datetime.datetime.now(datetime.UTC).isoformat()
        state.pop("completed_orgs", None)
        save_state(state)

        print("\n=== Phase 2: CLOSED sweep ===")
        closed_count = sweep_closed_bids()
        print(f"  {closed_count} bid(s) transitioned to CLOSED.")

        print("\n=== Phase 3: Score pending bids ===")
        delta_bid_numbers, skipped = score_pending_bids()
        print(f"  Skipped (rejected/closed): {skipped}")

        # Review delta = newly scored + extended + any scored-but-not-yet-exported from prior runs
        seen = set(delta_bid_numbers)
        review_bid_numbers = list(delta_bid_numbers)
        for bn in extended_bid_numbers:
            if bn not in seen:
                review_bid_numbers.append(bn)
                seen.add(bn)
        for bn in get_unexported_pass1_bid_numbers():
            if bn not in seen:
                review_bid_numbers.append(bn)
                seen.add(bn)

        today = datetime.date.today().isoformat()
        export_to_excel(f"{EXPORTS_DIR}/bids_{today}.xlsx")
        export_pass1_delta(review_bid_numbers, f"{EXPORTS_DIR}/pass1_{today}.xlsx")
        mark_pass1_exported(review_bid_numbers)
        print(f"\nDone. Excel written to exports/bids_{today}.xlsx")
        print(f"Review delta:   exports/pass1_{today}.xlsx "
              f"({len(delta_bid_numbers)} new, {len(extended_bid_numbers)} extended)")

    elif cmd == "run-pass2":
        arg = sys.argv[2] if len(sys.argv) > 2 else None
        if not arg:
            print("Error: run-pass2 requires an argument.")
            print("  python gem_tool.py run-pass2 <excel_path>   # ingest file and run Pass 2")
            print("  python gem_tool.py run-pass2 --no-file      # skip ingest, use existing DB flags")
            sys.exit(1)

        if arg == "--no-file":
            print("=== Phase 0: Skipping ingest (--no-file) ===")
        else:
            excel_path = Path(arg)
            if not excel_path.exists():
                print(f"Error: file not found: {excel_path}")
                sys.exit(1)
            print(f"=== Phase 0: Ingesting {excel_path} ===")
            ingest_excel(str(excel_path), force=True)

        print("\n=== Pipeline 2: Doc Fetch + Pass 2 Score ===")
        today  = datetime.date.today().isoformat()
        scored = run_pipeline2()
        print(f"Pass 2 delta:   exports/pass2_{today}.xlsx ({len(scored)} bids scored)")

    elif cmd == "ingest-excel":
        path = sys.argv[2] if len(sys.argv) > 2 else None
        if path:
            ingest_excel(path, force=True)
        else:
            ingest_all_pending()

    elif cmd == "export-excel":
        today = datetime.date.today().isoformat()
        export_to_excel(f"{EXPORTS_DIR}/bids_{today}.xlsx")
        print(f"Exported: exports/bids_{today}.xlsx")

    elif cmd == "score-pending":
        delta_bid_numbers, skipped = score_pending_bids()
        seen = set(delta_bid_numbers)
        all_to_export = list(delta_bid_numbers)
        for bn in get_unexported_pass1_bid_numbers():
            if bn not in seen:
                all_to_export.append(bn)
                seen.add(bn)
        today = datetime.date.today().isoformat()
        export_to_excel(f"{EXPORTS_DIR}/bids_{today}.xlsx")
        export_pass1_delta(all_to_export, f"{EXPORTS_DIR}/pass1_{today}.xlsx")
        mark_pass1_exported(all_to_export)
        print(f"Done. Excel written to exports/bids_{today}.xlsx")
        print(f"Pass 1 delta:   exports/pass1_{today}.xlsx "
              f"({len(delta_bid_numbers)} new bids, {skipped} skipped)")

    elif cmd == "add-rule":
        if len(sys.argv) < 4:
            print("Usage: gem_tool.py add-rule \"<pattern>\" \"<reason>\"")
            print("Example: gem_tool.py add-rule \"Sodium Chloride\" \"Medical supplies — out of scope\"")
            sys.exit(1)
        pattern = sys.argv[2].strip()
        reason  = sys.argv[3].strip()
        from modules.db import add_exclusion_rule
        add_exclusion_rule(pattern, reason, source="manual")
        print(f"  [added] '{pattern}' → {reason}")
        print("\nAll current rules:")
        from modules.db import get_exclusion_rules
        for r in get_exclusion_rules():
            print(f"  [{r['source']}] '{r['pattern']}' → {r['reason']}")

    elif cmd == "show-rules":
        from modules.db import get_exclusion_rules
        for r in get_exclusion_rules():
            print(f"  [{r['source']}] '{r['pattern']}' → {r['reason']}")

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()

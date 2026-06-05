"""Minimal sequential orchestrator launcher.

S2 wires up all three portals. ``run`` shells out (via each ``PortalAdapter``) to
the portal's ``scrape-score`` pipeline STRICTLY SEQUENTIALLY in the
``config.PORTALS`` order (HAL -> ISRO -> GeM) — one heavy op at a time — printing
each :class:`RunResult` and writing the captured subprocess log under
``$BIDPLUS_RUNTIME_DIR/logs/``. ``explain <portal> <pk...>`` prints the per-portal
dry-run view (input fields -> assembled prompt -> stored Pass-1 result).

The single ANTHROPIC_API_KEY comes from :mod:`bidplus.config` (the one .env);
each adapter injects it plus BIDPLUS_RUNTIME_DIR into its subprocess env. No
parent.db (S3) and no scrape_runs (S4) yet.

Run as:  python -m bidplus.launcher run
         python -m bidplus.launcher explain hal <tender_number> <line_number>
         python -m bidplus.launcher explain isro <tender_id>
         python -m bidplus.launcher explain gem <bid_number>
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time

import bidplus.config as config
from bidplus.adapters.base import RunResult
from bidplus.adapters.gem import GeMAdapter
from bidplus.adapters.hal import HALAdapter
from bidplus.adapters.isro import ISROAdapter

_ADAPTERS = {"hal": HALAdapter, "isro": ISROAdapter, "gem": GeMAdapter}


def _logs_dir():
    d = config.RUNTIME_DIR / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _print_result(result: RunResult, merge_counts: dict | None) -> None:
    print(f"\n[launcher] RunResult ({result.portal}):")
    print(f"  status        : {result.status}")
    print(f"  new_count     : {result.new_count}")
    print(f"  updated_count : {result.updated_count}")
    print(f"  closed_count  : {result.closed_count}")
    print(f"  scored_count  : {result.scored_count}")
    print(f"  stage_timings : {result.stage_timings}")
    if merge_counts is not None:
        print(f"  merge         : {merge_counts}")
    if result.error_summary:
        print(f"  error_summary :\n{result.error_summary}")


def _print_gate(g: dict) -> None:
    t = g["totals"]
    print("\n[gate] tiered buckets (compute only — S6 consumes):")
    print(f"  auto_summarize (5)  : {t['auto_summarize']}")
    print(f"  local_extract  (4)  : {t['local_extract']}")
    print(f"  on_demand     (<=3) : {t['on_demand']}")
    print(f"  excluded CLOSED     : {t['excluded_closed']}")
    print(f"  excluded keyword    : {t['excluded_keyword']}")


def cmd_run(_args: argparse.Namespace) -> int:
    """Run the full nightly cycle STRICTLY SEQUENTIALLY (HAL -> ISRO -> GeM).

    Per portal: scrape -> Pass 1 (subprocess) -> merge into parent.db -> record a
    scrape_runs row. The cycle opens with an in-progress overall scrape_runs row
    (finished_at NULL) and finalizes it at the end; a failed portal does NOT abort the
    others, and a partial/failed cycle raises a sticky system_alerts row. Finally the
    tiered gate buckets the merged bids for S6. Exit code is non-zero unless every
    portal succeeded.
    """
    from bidplus import gate as gate_mod
    from bidplus import merge as merge_mod
    from bidplus import runs

    print(f"[launcher] Sequential run order: {' -> '.join(config.PORTALS)}", flush=True)
    parent = merge_mod.connect_parent()
    merge_mod.ensure_shared(parent)

    cycle_start = runs._now()
    overall_id = runs.start_cycle(parent)
    print(f"[launcher] scrape_runs cycle id={overall_id} (status=running, finished_at=NULL)")

    results: list[RunResult] = []
    timings: dict[str, float] = {}
    for portal in config.PORTALS:
        print(f"\n[launcher] Running '{portal}' pipeline…", flush=True)
        adapter = _ADAPTERS[portal]()
        p_start = runs._now()
        t0 = time.monotonic()
        try:
            result = adapter.run_pipeline()
        except Exception as e:  # isolation: one portal's crash must not abort the cycle
            result = RunResult(
                portal=portal, status="failed",
                error_summary=f"{type(e).__name__}: {e}",
            )

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        (_logs_dir() / f"{portal}_{ts}.log").write_text(
            adapter.last_output or "(no subprocess output captured)\n"
        )

        merge_counts: dict | None = None
        merge_elapsed = 0.0
        if result.status != "failed":
            m0 = time.monotonic()
            try:
                merge_counts = merge_mod.merge_portal(portal, parent=parent)
            except Exception as e:
                merge_counts = {"error": f"{type(e).__name__}: {e}"}
            merge_elapsed = time.monotonic() - m0

        timings[portal] = round(time.monotonic() - t0, 3)
        runs.record_portal(parent, result, p_start, runs._now(),
                           {"merge": round(merge_elapsed, 3)})
        _print_result(result, merge_counts)
        results.append(result)

    g0 = time.monotonic()
    g = gate_mod.tiered_gate(parent)
    timings["gate"] = round(time.monotonic() - g0, 3)

    status = runs.finalize_cycle(parent, overall_id, results, cycle_start, timings)
    _print_gate(g)
    print(f"\n[launcher] Cycle {overall_id} finalized: status={status}")
    if status in ("partial", "failed"):
        print("[launcher] Sticky system_alerts row raised (clear it in the web app).")
    parent.close()
    return 0 if status == "success" else 1


def cmd_gate(_args: argparse.Namespace) -> int:
    """Print the tiered gate buckets over the current parent.db (no scrape, no Sonnet)."""
    from bidplus import gate as gate_mod
    from bidplus import merge as merge_mod

    parent = merge_mod.connect_parent()
    try:
        g = gate_mod.tiered_gate(parent)
    finally:
        parent.close()
    for p, d in g["per_portal"].items():
        print(
            f"[gate] {p:5} auto5={d['auto_summarize']:5} local4={d['local_extract']:5} "
            f"on_demand={d['on_demand']:6} closed={d['excluded_closed']:4} "
            f"keyword={d['excluded_keyword']:5}"
        )
    _print_gate(g)
    return 0


def cmd_run_status(_args: argparse.Namespace) -> int:
    """Report whether a cycle is in progress (finished_at IS NULL) + sticky alerts.

    Exit 0 = idle (safe to deploy), 1 = a run is in progress. Powers the deploy guard.
    """
    from bidplus import merge as merge_mod
    from bidplus import runs

    parent = merge_mod.connect_parent()
    try:
        merge_mod.ensure_shared(parent)
        row = runs.active_run(parent)
        alerts = runs.active_alerts(parent)
    finally:
        parent.close()

    if row is None:
        print("run-status: idle (no in-progress cycle)")
    else:
        print(f"run-status: RUNNING (scrape_runs id={row['id']}, started_at={row['started_at']})")
    print(f"active sticky alerts: {len(alerts)}")
    for a in alerts:
        print(f"  - alert id={a['id']} run_id={a['run_id']} raised_at={a['raised_at']}: {a['reason']}")
    return 1 if row is not None else 0


def cmd_merge(args: argparse.Namespace) -> int:
    """Upsert-merge each tool bids.db into parent.db (one table per portal).

    Idempotent: a second merge with no tool changes reports 0 inserted / 0 updated.
    With --check, re-compares each parent table against its tool DB afterwards.
    """
    from bidplus import merge as merge_mod

    portals = args.portals or list(config.PORTALS)
    results = merge_mod.merge_all(portals)
    for r in results:
        print(
            f"[merge] {r['portal']:5} tool_rows={r['tool_rows']:6} "
            f"inserted={r['inserted']:6} updated={r['updated']:6} "
            f"unchanged={r['unchanged']:6}"
        )

    rc = 0
    if args.check:
        print("[merge] --check: comparing parent tables against tool DBs…")
        for portal in portals:
            c = merge_mod.compare_portal(portal)
            ok = c["missing_in_parent"] == 0 and c["value_mismatches"] == 0
            print(
                f"[check] {c['portal']:5} tool_rows={c['tool_rows']:6} "
                f"parent_rows={c['parent_rows']:6} missing={c['missing_in_parent']} "
                f"mismatches={c['value_mismatches']}  {'OK' if ok else 'FAIL'}"
            )
            for s in c["sample"]:
                print(f"          - {s}")
            rc = rc or (0 if ok else 1)
    return rc


def cmd_explain(args: argparse.Namespace) -> int:
    adapter_cls = _ADAPTERS.get(args.portal)
    if adapter_cls is None:
        print(f"Error: unknown portal {args.portal!r}", file=sys.stderr)
        return 1
    # Uniform source-PK encoding: HAL takes <tender_number> <line_number> joined by
    # '|' (the HAL adapter splits on it); ISRO/GeM take a single id (join is a no-op).
    source_pk = "|".join(args.source_pk)
    adapter = adapter_cls()
    payload = adapter.explain(source_pk)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bidplus.launcher",
        description="Teclever bid-portal orchestrator launcher (S2: HAL -> ISRO -> GeM).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser(
        "run", help="Run scrape -> CLOSED sweep -> Pass 1 for all portals, sequentially."
    )
    p_run.set_defaults(func=cmd_run)

    p_merge = sub.add_parser(
        "merge", help="Upsert-merge each tool bids.db into parent.db (one table per portal)."
    )
    p_merge.add_argument(
        "portals", nargs="*", choices=sorted(_ADAPTERS),
        help="Portals to merge (default: all, in PORTALS order).",
    )
    p_merge.add_argument(
        "--check", action="store_true",
        help="After merging, compare each parent table against its tool DB.",
    )
    p_merge.set_defaults(func=cmd_merge)

    p_gate = sub.add_parser(
        "gate", help="Print the tiered-gate buckets over parent.db (no scrape, no Sonnet)."
    )
    p_gate.set_defaults(func=cmd_gate)

    p_status = sub.add_parser(
        "run-status", help="Report in-progress cycle (finished_at IS NULL) + sticky alerts."
    )
    p_status.set_defaults(func=cmd_run_status)

    p_explain = sub.add_parser(
        "explain", help="Print the dry-run view for one bid (no API call)."
    )
    p_explain.add_argument("portal", choices=sorted(_ADAPTERS), help="Portal name.")
    p_explain.add_argument(
        "source_pk",
        nargs="+",
        help="Source PK — HAL: <tender_number> <line_number>; ISRO: <tender_id>; GeM: <bid_number>.",
    )
    p_explain.set_defaults(func=cmd_explain)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

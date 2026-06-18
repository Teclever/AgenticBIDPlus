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
from bidplus.adapters.halc import HALCAdapter
from bidplus.adapters.isro import ISROAdapter

_ADAPTERS = {"hal": HALAdapter, "halc": HALCAdapter, "isro": ISROAdapter, "gem": GeMAdapter}


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


def _run_pass2(summarize_mod, gate_mod, parent, portal: str) -> dict:
    """S6 Pass 2 for ONE portal: summarize the score-5 auto queue (the single Sonnet path) and
    locally extract the score-4 queue (NO Sonnet). Per-bid isolation — one bad bid logs and is
    skipped, never aborting the phase; a billing/usage ``SystemExit`` DOES propagate to abort
    the cycle. Idempotent via the gate predicates (already-done bids are not in the queue)."""
    from bidplus import locks

    q = gate_mod.work_pks(parent, portal)
    counts: dict = {"summarized": 0, "summary_failed": 0, "local_extracted": 0, "failed_pks": []}
    # Hold the global summarization lock for the whole score-5 loop so a concurrent web
    # "Generate Summary" click is told the system is busy (WEBAPP_DESIGN §16.8) — the one
    # path to Sonnet is never entered twice at once. local_extract (no Sonnet) stays outside.
    with locks.summarize_lock(blocking=True):
        for pk in q["auto_summarize"]:
            try:
                r = summarize_mod.summarize_bid(portal, pk, parent, fetch=True)
            except SystemExit:
                raise
            except Exception as e:
                counts["summary_failed"] += 1
                counts["failed_pks"].append(str(pk))
                print(f"  [pass2] {portal} {pk} summarize error: {type(e).__name__}: {e}")
                continue
            if r.get("status") == "failed":
                counts["summary_failed"] += 1
                counts["failed_pks"].append(str(pk))
            else:
                counts["summarized"] += 1
    for pk in q["local_extract"]:
        try:
            summarize_mod.local_extract_bid(portal, pk, parent, fetch=True)
            counts["local_extracted"] += 1
        except SystemExit:
            raise
        except Exception as e:
            print(f"  [pass2] {portal} {pk} local-extract error: {type(e).__name__}: {e}")
    return counts


def cmd_run(args: argparse.Namespace) -> int:
    """Run the full nightly cycle STRICTLY SEQUENTIALLY (HAL -> ISRO -> GeM).

    At cycle start the orchestrator applies any operator-approved eliminator list changes
    from list_review/ready/ (governance), then per portal: scrape (thin tool, no in-tool
    Pass 1) -> centralized Pass 1 (two-pass eliminator HARD + Haiku, bidplus.scoring) ->
    merge into parent.db -> record a scrape_runs row. The cycle opens with an in-progress
    overall scrape_runs row and finalizes it; a failed portal does NOT abort the others, and
    a partial/failed cycle raises a sticky system_alerts row. Finally the tiered gate buckets
    the merged bids for S6, and a due AI delta is flagged. --shadow keeps the eliminator
    non-destructive (logs would-eliminate, still scores via Haiku). Exit non-zero unless every
    portal succeeded.
    """
    from bidplus import eliminator
    from bidplus import gate as gate_mod
    from bidplus import governance
    from bidplus import lifecycle
    from bidplus import merge as merge_mod
    from bidplus import runs
    from bidplus import scoring
    from bidplus import summarize as summarize_mod

    mode = "shadow" if args.shadow else "hard"
    print(f"[launcher] Sequential run order: {' -> '.join(config.PORTALS)}  (eliminator={mode})", flush=True)
    parent = merge_mod.connect_parent()
    merge_mod.ensure_shared(parent)
    eliminator.seed_terms(parent)  # idempotent first-deploy seed; no-op once populated

    ing = governance.ingest_ready(parent)
    print(f"[launcher] governance ingest (list_review/ready/): files={ing['files']} "
          f"applied={ing['applied']} rejected={ing['rejected']}")

    cycle_start = runs._now()
    overall_id = runs.start_cycle(parent)
    print(f"[launcher] scrape_runs cycle id={overall_id} (status=running, finished_at=NULL)")

    results: list[RunResult] = []
    timings: dict[str, float] = {}
    pass2_totals = {"local_extracted": 0, "summarized": 0, "summary_failed": 0}
    for portal in config.PORTALS:
        print(f"\n[launcher] Running '{portal}' pipeline…", flush=True)
        adapter = _ADAPTERS[portal]()
        p_start = runs._now()
        t0 = time.monotonic()
        try:
            result = adapter.run_pipeline()  # scrape-only now
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
        score_info: dict | None = None
        pass2: dict | None = None
        score_elapsed = merge_elapsed = pass2_elapsed = 0.0
        if result.status != "failed":
            adapter = _ADAPTERS[portal]()
            pk_cols = tuple(adapter._SCORING["pk"])

            s0 = time.monotonic()
            try:
                score_info = scoring.score_portal(portal, parent, mode=mode)
                result.keyword_scored_count = score_info.get("keyword_eliminated", 0)
                result.model_scored_count = score_info.get("model_scored", 0)
                result.scored_count = result.keyword_scored_count + result.model_scored_count
                runs.auto_clear_scoring_alerts(
                    parent, portal, str(adapter.tool_db_path()), pk_cols)
                if score_info.get("unscored_left", 0) > 0:
                    runs.raise_typed_alert(
                        parent, overall_id, "SCORING_FAILURE", portal,
                        score_info.get("unscored_ids", []),
                        f"{score_info['unscored_left']} bid(s) could not be scored after retries",
                    )
            except SystemExit as e:
                runs.raise_typed_alert(
                    parent, overall_id, "CREDIT_EXHAUSTED", portal, [],
                    f"Anthropic billing/usage limit reached: {str(e)[:300]}",
                )
                raise
            except Exception as e:
                score_info = {"error": f"{type(e).__name__}: {e}"}
                result.status = "partial"
            score_elapsed = time.monotonic() - s0

            m0 = time.monotonic()
            try:
                merge_counts = merge_mod.merge_portal(portal, parent=parent)
            except Exception as e:
                merge_counts = {"error": f"{type(e).__name__}: {e}"}
            merge_elapsed = time.monotonic() - m0

            # S6 Pass 2 (one heavy op at a time, right after this portal's merge): summarize
            # the score-5 queue via Sonnet + locally extract the score-4 queue (no Sonnet).
            q0 = time.monotonic()
            try:
                pass2 = _run_pass2(summarize_mod, gate_mod, parent, portal)
            except SystemExit as e:
                runs.raise_typed_alert(
                    parent, overall_id, "CREDIT_EXHAUSTED", portal, [],
                    f"Anthropic billing/usage limit reached during summarization: {str(e)[:300]}",
                )
                raise
            pass2_elapsed = time.monotonic() - q0
            for k in ("summarized", "summary_failed", "local_extracted"):
                pass2_totals[k] += pass2[k]
            if pass2.get("summary_failed", 0) > 0:
                runs.raise_typed_alert(
                    parent, overall_id, "SUMMARY_FAILURE", portal,
                    pass2.get("failed_pks", []),
                    f"{pass2['summary_failed']} AI summary/ies failed",
                )
            runs.auto_clear_summary_alerts(parent, portal, pk_cols)

        timings[portal] = round(time.monotonic() - t0, 3)
        runs.record_portal(parent, result, p_start, runs._now(),
                           {"score": round(score_elapsed, 3), "merge": round(merge_elapsed, 3),
                            "summarize": round(pass2_elapsed, 3)}, pass2=pass2)
        _print_result(result, merge_counts)
        if score_info is not None:
            print(f"  score         : {score_info}")
        if pass2 is not None:
            print(f"  pass2 (S6)    : {pass2}")
        results.append(result)

    g0 = time.monotonic()
    g = gate_mod.tiered_gate(parent)
    timings["gate"] = round(time.monotonic() - g0, 3)

    # S7 housekeeping (terminal, idempotent): mark past-closing bids CLOSED + drop their files,
    # run the N-day retention sweep, reap orphaned dirs. Runs LAST so a freshly past-closing bid
    # settles CLOSED for the day even if this cycle's merge briefly re-opened it.
    sw0 = time.monotonic()
    sweep = lifecycle.run_sweep(parent)
    timings["sweep"] = round(time.monotonic() - sw0, 3)
    print(f"[launcher] sweep (S7): {sweep}")

    status = runs.finalize_cycle(parent, overall_id, results, cycle_start, timings,
                                 pass2_totals=pass2_totals)
    _print_gate(g)
    print(f"[launcher] Pass 2 (S6) totals: {pass2_totals}")
    budget = lifecycle.budget_report(parent)
    print(f"[launcher] overnight budget: {budget}")
    if not budget.get("within_budget", True):
        print("[launcher] ⚠ cycle finished AFTER the overnight deadline — review stage timings.")
    print(f"\n[launcher] Cycle {overall_id} finalized: status={status}")
    if status in ("partial", "failed"):
        print("[launcher] Sticky system_alerts row raised (clear it in the web app).")
    if governance.should_run_delta(parent):
        print("[launcher] Eliminator AI delta is DUE — run `governance-delta` to stage "
              "proposals for Excel review (list_review/pending/).")
    parent.close()
    return 0 if status == "success" else 1


def cmd_summarize(args: argparse.Namespace) -> int:
    """On-demand S6 Pass 2 for specific bids (the web app's "Retrieve information" trigger).

    Default runs the §8b Sonnet module (real API spend). ``--local-only`` runs the score-4
    local extraction instead (no Sonnet). ``--no-fetch`` uses the already-staged files without
    re-fetching (the score-4 "sim click" case: summarize from stored docs). Each ``bid_id`` is a
    '|'-joined source PK (HAL: tender|line; ISRO/GeM: the single id)."""
    from bidplus import merge as merge_mod
    from bidplus import summarize as summarize_mod

    parent = merge_mod.connect_parent()
    rc = 0
    try:
        for pk in args.bid_id:
            if args.local_only:
                r = summarize_mod.local_extract_bid(args.portal, pk, parent, fetch=not args.no_fetch)
            else:
                r = summarize_mod.summarize_bid(args.portal, pk, parent, fetch=not args.no_fetch)
                if r.get("status") == "failed":
                    rc = 1
            print(f"[summarize] {r}")
    finally:
        parent.close()
    return rc


def cmd_sweep(_args: argparse.Namespace) -> int:
    """Run the S7 housekeeping pass standalone (CLOSED sweep + N-day retention + orphan reaping)
    and print the overnight-budget report for the latest cycle. Idempotent; no scrape, no Sonnet."""
    from bidplus import lifecycle
    from bidplus import merge as merge_mod

    parent = merge_mod.connect_parent()
    try:
        merge_mod.ensure_shared(parent)
        res = lifecycle.run_sweep(parent)
        for stage, per_portal in res.items():
            print(f"[sweep] {stage}: {per_portal}")
        print(f"[sweep] budget: {lifecycle.budget_report(parent)}")
    finally:
        parent.close()
    return 0


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


def cmd_singletender_backfill(_args: argparse.Namespace) -> int:
    """Scan existing staging-dir .txt files for Single Tender fields and update parent.db.
    No downloads — only processes bids that already have .txt files on disk."""
    from bidplus import merge as merge_mod
    from bidplus import summarize as sum_mod
    from bidplus.web import mapping as mapping_mod

    parent = merge_mod.connect_parent()
    merge_mod.ensure_shared(parent)

    total_found = 0
    for portal in config.PORTALS:
        rows = parent.execute(
            f"SELECT * FROM {portal}_bids WHERE COALESCE(is_single_tender, 0) = 0"
        ).fetchall()
        found = 0
        for row in rows:
            row_dict = {k: row[k] for k in row.keys()}
            source_pk = mapping_mod.bid_key(row_dict, portal)
            text = sum_mod._read_staging_text(portal, source_pk)
            if not text:
                continue
            is_st, org = sum_mod._detect_single_tender(text)
            if not is_st:
                continue
            cls = sum_mod._st_class(org)
            sum_mod._apply_single_tender_db(parent, portal, source_pk, org, cls)
            found += 1
            print(f"  [{portal}] {source_pk}: class={cls} org={org!r}")
        print(f"[singletender-backfill] {portal}: {found} single tender bids detected and updated")
        total_found += found

    print(f"[singletender-backfill] total: {total_found}")
    return 0


def cmd_boost_backfill(_args: argparse.Namespace) -> int:
    """Promote existing bids matching a boost phrase (e.g. 'test rig') to score 5.
    Scope: user_state='new' only — closed/accepted/rejected bids are left alone.
    Writes BOTH the tool DB and parent.db (the merge mirrors tool-owned scoring
    columns, so a parent-only update would be clobbered on the next merge)."""
    import sqlite3 as _sqlite3

    from bidplus import eliminator
    from bidplus import merge as merge_mod

    parent = merge_mod.connect_parent()
    merge_mod.ensure_shared(parent)
    eliminator.ensure_boost_seed(parent)
    terms = eliminator.load_terms(parent)
    if not terms.boost_phrases:
        print("[boost-backfill] no active boost phrases — nothing to do")
        return 0
    print(f"[boost-backfill] boost phrases: {terms.boost_phrases}")

    total = 0
    for portal in config.PORTALS:
        adapter = _ADAPTERS[portal]()
        spec = adapter._SCORING
        tool_table, pk_cols, text_col = spec["table"], tuple(spec["pk"]), spec["text"]
        ptable = f"{portal}_bids"
        pk_where = " AND ".join(f"{c}=?" for c in pk_cols)

        rows = parent.execute(
            f"SELECT {', '.join(pk_cols)}, {text_col} AS t, pass1_score, pass1_rationale "
            f"FROM {ptable} WHERE COALESCE(user_state,'new')='new' "
            f"AND COALESCE(bid_status,'') <> 'CLOSED' "
            f"AND pass1_score IS NOT NULL AND pass1_score < 5"
        ).fetchall()

        matches = []
        for r in rows:
            term = eliminator.boost_match(r["t"], terms.boost_phrases)
            if term:
                matches.append((r, term))
        if not matches:
            print(f"[boost-backfill] {portal}: 0 matches")
            continue

        tool = _sqlite3.connect(adapter.tool_db_path())
        try:
            for r, term in matches:
                pk_vals = tuple(r[c] for c in pk_cols)
                rationale = f"[auto-promoted: {term}] {r['pass1_rationale'] or ''}".strip()
                set_sql = ("SET pass1_score=5, pass1_method='model', "
                           "pass1_eliminated_by=NULL, auto_rejected=0, pass1_rationale=?")
                tool.execute(f"UPDATE {tool_table} {set_sql} WHERE {pk_where}",
                             (rationale, *pk_vals))
                parent.execute(f"UPDATE {ptable} {set_sql} WHERE {pk_where}",
                               (rationale, *pk_vals))
                print(f"  [{portal}] {'|'.join(str(v) for v in pk_vals)}: "
                      f"score {r['pass1_score']} → 5 ({term})")
            tool.commit()
            parent.commit()
        finally:
            tool.close()
        print(f"[boost-backfill] {portal}: {len(matches)} bid(s) promoted to 5")
        total += len(matches)

    print(f"[boost-backfill] total promoted: {total} "
          f"(unsummarized ones will be Sonnet-summarized on the next nightly run)")
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


def cmd_eliminate(args: argparse.Namespace) -> int:
    """SHADOW analysis of the two-pass eliminator gate (no writes, no model calls).

    Seeds eliminator_terms from the mined JSON if empty (idempotent), then runs the gate
    over each portal's bids and reports would-eliminate counts, positive-veto saves, and
    the CUTOVER GATE: zero eliminations of any bid that historically scored >=3.
    """
    from bidplus import eliminator
    from bidplus import merge as merge_mod

    parent = merge_mod.connect_parent()
    try:
        seeded = eliminator.seed_terms(parent)
        t = eliminator.load_terms(parent)
        print(f"[eliminate] seed: {seeded}")
        print(f"[eliminate] terms: neg_phrases={len(t.neg_phrases)} neg_words={len(t.neg_words)} "
              f"guarded={len(t.guarded)} pos_phrases={len(t.pos_phrases)} "
              f"pos_tokens={len(t.pos_tokens)} stop={len(t.stop)}")

        portals = args.portals or list(config.PORTALS)
        grand = {"total": 0, "would_eliminate": 0, "score_ge3_collisions": 0, "pos_vetoed": 0}
        for portal in portals:
            recs = _ADAPTERS[portal]().scoring_records()
            rep = eliminator.shadow_report(recs, t)
            for k in grand:
                grand[k] += rep[k]
            pct = 100 * rep["would_eliminate"] / max(rep["total"], 1)
            print(f"[shadow] {portal:5} bids={rep['total']:6} "
                  f"would_eliminate={rep['would_eliminate']:6} ({pct:4.1f}%) "
                  f"pos_vetoed={rep['pos_vetoed']:5} score>=3_collisions={rep['score_ge3_collisions']}")

        pct = 100 * grand["would_eliminate"] / max(grand["total"], 1)
        print(f"[shadow] TOTAL bids={grand['total']} would_eliminate={grand['would_eliminate']} "
              f"({pct:.1f}%) pos_vetoed={grand['pos_vetoed']} "
              f"score>=3_collisions={grand['score_ge3_collisions']}")
        ok = grand["score_ge3_collisions"] == 0
        print(f"[shadow] CUTOVER GATE: {'PASS (zero score>=3 eliminated)' if ok else 'FAIL'}")
    finally:
        parent.close()
    return 0 if ok else 1


def cmd_score(args: argparse.Namespace) -> int:
    """Centralized Pass-1: eliminator gate + Haiku scoring for ONE portal (writes to its
    tool DB). --mode shadow keeps the eliminator non-destructive; --limit caps the batch
    (use a small number for a live smoke test). Real API spend.
    """
    from bidplus import merge as merge_mod
    from bidplus import scoring

    parent = merge_mod.connect_parent()
    try:
        r = scoring.score_portal(args.portal, parent, mode=args.mode,
                                 limit=args.limit, rescore=args.rescore)
    finally:
        parent.close()
    print(f"[score] {r['portal']} mode={r['mode']} candidates={r['candidates']} "
          f"would_eliminate={r['would_eliminate']} model_scored={r['model_scored']} "
          f"keyword_eliminated={r['keyword_eliminated']} unscored_left={r['unscored_left']}")
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    """Human PROMOTE of a soft-flagged bid (confirmed false-elimination): records
    false_positives on its matched terms, marks it promoted, and requeues it for Pass 1.
    A high-support term is NEVER auto-quarantined (fix via a positive add)."""
    from bidplus import governance
    from bidplus import merge as merge_mod

    parent = merge_mod.connect_parent()
    try:
        for bid_id in args.bid_id:
            r = governance.promote(parent, args.portal, bid_id, args.reason)
            print(f"[promote] {args.portal} {bid_id}: false_positives++ for {r['false_positives_for']} "
                  f"-> statuses={r['statuses']} (requeued for Pass 1)")
    finally:
        parent.close()
    return 0


def cmd_accept(args: argparse.Namespace) -> int:
    """ACCEPT / CLEAR-TABLE: confirm undisposed auto-rejected bids as correct rejections
    (confirmed_rejections++). With no bid_id, clears the whole portal table."""
    from bidplus import governance
    from bidplus import merge as merge_mod

    parent = merge_mod.connect_parent()
    try:
        r = governance.accept(parent, args.portal, args.bid_id or None)
    finally:
        parent.close()
    print(f"[accept] {r['portal']}: confirmed {r['accepted']} rejection(s)")
    return 0


def cmd_governance_delta(args: argparse.Namespace) -> int:
    """Run the periodic AI delta: emit ADD/REMOVE/REFINE proposals from accumulated
    promotion reasons, keep-guard them, stage to list_change_proposals, and export a
    risk-coded Excel to list_review/pending/. Real API spend (Sonnet)."""
    from bidplus import governance
    from bidplus import merge as merge_mod

    parent = merge_mod.connect_parent()
    try:
        if not args.force and not governance.should_run_delta(parent):
            print("[governance-delta] not due (no new promotions, or under threshold/week). "
                  "Use --force to run anyway.")
            return 0
        r = governance.generate_delta(parent)
    finally:
        parent.close()
    print(f"[governance-delta] batch={r['batch_id']} proposed={r['proposed']} kept={r['kept']} "
          f"blocked_by_guard={r['blocked_by_guard']} promotions_used={r['promotions_used']}")
    if r["excel"]:
        print(f"[governance-delta] review Excel: {r['excel']}  (edit, then move to list_review/ready/)")
    return 0


def cmd_governance_apply(args: argparse.Namespace) -> int:
    """Ingest operator-approved list changes from list_review/ready/ and apply them to
    eliminator_terms transactionally (also run automatically at the start of `run`)."""
    from bidplus import governance
    from bidplus import merge as merge_mod

    parent = merge_mod.connect_parent()
    try:
        r = governance.ingest_ready(parent)
    finally:
        parent.close()
    print(f"[governance-apply] files={r['files']} applied={r['applied']} rejected={r['rejected']}")
    return 0


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
        "run", help="Full cycle: governance ingest -> per portal scrape -> centralized Pass 1 "
                    "(eliminator hard + Haiku) -> merge -> gate, sequentially."
    )
    p_run.add_argument(
        "--shadow", action="store_true",
        help="Keep the eliminator non-destructive (log would-eliminate, still Haiku-score).",
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

    p_summarize = sub.add_parser(
        "summarize", help="On-demand S6 Pass 2 for specific bids (§8b module). Real API spend."
    )
    p_summarize.add_argument("portal", choices=sorted(_ADAPTERS))
    p_summarize.add_argument("bid_id", nargs="+", help="'|'-joined PK (HAL: tender|line).")
    p_summarize.add_argument("--no-fetch", action="store_true",
                             help="Use already-staged files; do not re-fetch (sim 'Retrieve' click).")
    p_summarize.add_argument("--local-only", action="store_true",
                             help="Run score-4 local extraction only (NO Sonnet).")
    p_summarize.set_defaults(func=cmd_summarize)

    p_gate = sub.add_parser(
        "gate", help="Print the tiered-gate buckets over parent.db (no scrape, no Sonnet)."
    )
    p_gate.set_defaults(func=cmd_gate)

    p_sweep = sub.add_parser(
        "sweep", help="S7 housekeeping: CLOSED sweep + N-day file retention + orphan reaping."
    )
    p_sweep.set_defaults(func=cmd_sweep)

    p_status = sub.add_parser(
        "run-status", help="Report in-progress cycle (finished_at IS NULL) + sticky alerts."
    )
    p_status.set_defaults(func=cmd_run_status)

    p_elim = sub.add_parser(
        "eliminate", help="SHADOW analysis of the two-pass eliminator gate (no writes)."
    )
    p_elim.add_argument(
        "portals", nargs="*", choices=sorted(_ADAPTERS),
        help="Portals to analyse (default: all).",
    )
    p_elim.set_defaults(func=cmd_eliminate)

    p_score = sub.add_parser(
        "score", help="Centralized Pass-1 (eliminator gate + Haiku) for one portal. API spend."
    )
    p_score.add_argument("portal", choices=sorted(_ADAPTERS), help="Portal to score.")
    p_score.add_argument("--mode", choices=("shadow", "hard"), default="hard",
                         help="hard (default) = keyword-eliminate; shadow = log only, still score.")
    p_score.add_argument("--limit", type=int, default=None, help="Cap candidates (smoke test).")
    p_score.add_argument("--rescore", action="store_true",
                         help="Re-score all rows, not just pass1_score IS NULL.")
    p_score.set_defaults(func=cmd_score)

    p_promote = sub.add_parser(
        "promote", help="Promote a soft-flagged bid (false-elimination): ledger + requeue."
    )
    p_promote.add_argument("portal", choices=sorted(_ADAPTERS))
    p_promote.add_argument("bid_id", nargs="+", help="'|'-joined PK (HAL: tender|line).")
    p_promote.add_argument("--reason", required=True, help="Why this bid is in-scope (feeds the AI delta).")
    p_promote.set_defaults(func=cmd_promote)

    p_accept = sub.add_parser(
        "accept", help="Confirm auto-rejected bids as correct (clear-table if no bid_id)."
    )
    p_accept.add_argument("portal", choices=sorted(_ADAPTERS))
    p_accept.add_argument("bid_id", nargs="*", help="Specific bids; omit to clear the whole table.")
    p_accept.set_defaults(func=cmd_accept)

    p_gdelta = sub.add_parser(
        "governance-delta", help="Generate the AI list-change delta + Excel review file. API spend."
    )
    p_gdelta.add_argument("--force", action="store_true", help="Run even if not due.")
    p_gdelta.set_defaults(func=cmd_governance_delta)

    p_gapply = sub.add_parser(
        "governance-apply", help="Apply approved list changes from list_review/ready/."
    )
    p_gapply.set_defaults(func=cmd_governance_apply)

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

    p_st_backfill = sub.add_parser(
        "singletender-backfill",
        help="Scan existing .txt files for Single Tender field and update parent.db (no downloads).",
    )
    p_st_backfill.set_defaults(func=cmd_singletender_backfill)

    p_boost = sub.add_parser(
        "boost-backfill",
        help="Promote existing NEW bids matching a boost phrase (e.g. 'test rig') to score 5.",
    )
    p_boost.set_defaults(func=cmd_boost_backfill)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

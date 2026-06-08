"""Run logging + sticky alerts (S4).

The orchestrator records every nightly cycle in ``scrape_runs`` and raises a sticky
``system_alerts`` row on any failed/partial cycle.

Lifecycle (plan §7 / DEPLOY_WORKFLOW §3.1):
- At cycle start, INSERT one **overall** row (``tool IS NULL``, ``status='running'``,
  ``finished_at IS NULL``). The NULL ``finished_at`` is the live-run marker the deploy
  active-run guard checks — a live run is detected by state, not a stale terminal status.
- After each portal, INSERT a **per-tool** row with its counts + per-stage timings.
- At cycle end, finalize the overall row: ``success`` (all portals ok), ``failed`` (all
  failed), else ``partial``; write aggregate counts + finished_at.
- On ``partial``/``failed``, raise a **sticky** ``system_alerts`` row. It is cleared only
  by a human (web-app round) — a later successful cycle NEVER clears it.

This module owns only the bookkeeping; the launcher drives the sequence and the merge.
"""

from __future__ import annotations

import datetime
import json
import sqlite3

from bidplus.adapters.base import RunResult


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def start_cycle(parent: sqlite3.Connection) -> int:
    """INSERT the in-progress overall row and return its id."""
    cur = parent.execute(
        "INSERT INTO scrape_runs (started_at, finished_at, tool, status) "
        "VALUES (?, NULL, NULL, 'running')",
        (_now(),),
    )
    parent.commit()
    return int(cur.lastrowid)


def record_portal(parent: sqlite3.Connection, result: RunResult,
                  started_at: str, finished_at: str,
                  timings: dict[str, float] | None = None,
                  pass2: dict[str, int] | None = None) -> None:
    """INSERT one finalized per-tool row. Counts come from the portal's RunResult; the S6
    Pass-2 counts (``local_extracted``/``summarized``/``summary_failed``) come from ``pass2``
    (``{}`` / failed portals leave them 0)."""
    merged = dict(result.stage_timings or {})
    if timings:
        merged.update(timings)
    p2 = pass2 or {}
    parent.execute(
        "INSERT INTO scrape_runs (started_at, finished_at, tool, status, new_count, "
        "updated_count, closed_count, scored_count, local_extracted_count, "
        "summarized_count, summary_failed_count, error_summary, stage_timings_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (started_at, finished_at, result.portal, result.status, result.new_count,
         result.updated_count, result.closed_count, result.scored_count,
         p2.get("local_extracted", 0), p2.get("summarized", 0), p2.get("summary_failed", 0),
         result.error_summary, json.dumps(merged)),
    )
    parent.commit()


def finalize_cycle(parent: sqlite3.Connection, overall_id: int,
                   results: list[RunResult], started_at: str,
                   timings: dict[str, float] | None = None,
                   pass2_totals: dict[str, int] | None = None) -> str:
    """Finalize the overall row, then raise a sticky alert on partial/failed.

    ``pass2_totals`` carries the cycle-wide S6 counts (local_extracted/summarized/
    summary_failed) aggregated across portals. Returns the overall status.
    """
    statuses = [r.status for r in results]
    if statuses and all(s == "success" for s in statuses):
        status = "success"
    elif statuses and all(s == "failed" for s in statuses):
        status = "failed"
    else:
        status = "partial"

    errs = [f"{r.portal}: {r.error_summary}" for r in results
            if r.status != "success" and r.error_summary]
    error_summary = "; ".join(errs) or None

    p2 = pass2_totals or {}
    parent.execute(
        "UPDATE scrape_runs SET finished_at=?, status=?, new_count=?, updated_count=?, "
        "closed_count=?, scored_count=?, local_extracted_count=?, summarized_count=?, "
        "summary_failed_count=?, error_summary=?, stage_timings_json=? WHERE id=?",
        (_now(), status,
         sum(r.new_count for r in results),
         sum(r.updated_count for r in results),
         sum(r.closed_count for r in results),
         sum(r.scored_count for r in results),
         p2.get("local_extracted", 0), p2.get("summarized", 0), p2.get("summary_failed", 0),
         error_summary, json.dumps(timings or {}), overall_id),
    )
    parent.commit()

    if status in ("partial", "failed"):
        reason = f"Cycle {status}: " + (error_summary or "see scrape_runs")
        raise_alert(parent, overall_id, reason[:500])

    return status


def raise_alert(parent: sqlite3.Connection, run_id: int, reason: str) -> int:
    """INSERT a sticky CYCLE_FAILED/CYCLE_PARTIAL alert (backward-compat wrapper)."""
    cur = parent.execute(
        "INSERT INTO system_alerts (raised_at, run_id, reason, alert_type, status) "
        "VALUES (?, ?, ?, 'CYCLE_FAILED', 'active')",
        (_now(), run_id, reason),
    )
    parent.commit()
    return int(cur.lastrowid)


def raise_typed_alert(parent: sqlite3.Connection, run_id: int | None,
                      alert_type: str, portal: str | None,
                      bid_refs: list[str], reason: str) -> int:
    """INSERT a typed sticky alert with bid-level detail."""
    cur = parent.execute(
        "INSERT INTO system_alerts "
        "(raised_at, run_id, reason, alert_type, portal, bid_refs, status) "
        "VALUES (?,?,?,?,?,?,?)",
        (_now(), run_id, reason, alert_type, portal,
         json.dumps(bid_refs) if bid_refs else None, "active"),
    )
    parent.commit()
    return int(cur.lastrowid)


def list_alerts(parent: sqlite3.Connection, include_cleared: bool = False) -> list[sqlite3.Row]:
    """All alerts: active+retry_failed always; cleared only within the 10-day window."""
    if include_cleared:
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=10)).isoformat(timespec="seconds")
        return parent.execute(
            "SELECT * FROM system_alerts "
            "WHERE status IN ('active','retry_failed') "
            "OR (status='cleared' AND cleared_at >= ?) "
            "ORDER BY raised_at DESC",
            (cutoff,),
        ).fetchall()
    return parent.execute(
        "SELECT * FROM system_alerts WHERE status IN ('active','retry_failed') "
        "ORDER BY raised_at DESC"
    ).fetchall()


def clear_alert_group(parent: sqlite3.Connection, alert_ids: list[int],
                      user_id: int | None) -> None:
    """Mark a group of alerts cleared (success path)."""
    now = _now()
    for aid in alert_ids:
        parent.execute(
            "UPDATE system_alerts SET status='cleared', cleared_at=?, cleared_by=?, "
            "retry_count=retry_count+1, last_retry_at=?, last_retry_by=? WHERE id=?",
            (now, user_id, now, user_id, aid),
        )
    parent.commit()


def fail_alert_group(parent: sqlite3.Connection, alert_ids: list[int],
                     user_id: int, error: str) -> None:
    """Mark a group of alerts retry_failed (failure path)."""
    now = _now()
    for aid in alert_ids:
        parent.execute(
            "UPDATE system_alerts SET status='retry_failed', retry_count=retry_count+1, "
            "last_retry_at=?, last_retry_by=?, last_retry_error=? WHERE id=?",
            (now, user_id, error[:500], aid),
        )
    parent.commit()


def auto_clear_summary_alerts(parent: sqlite3.Connection, portal: str,
                               pk_cols: tuple) -> int:
    """After pass2: auto-clear SUMMARY_FAILURE alerts whose bid_refs are all now
    summary_status='done' in the parent table. Returns number of alerts cleared."""
    alerts = parent.execute(
        "SELECT id, bid_refs FROM system_alerts "
        "WHERE portal=? AND alert_type='SUMMARY_FAILURE' AND status IN ('active','retry_failed')",
        (portal,),
    ).fetchall()
    if not alerts:
        return 0
    table = f"{portal}_bids"
    pk_where = " AND ".join(f"{c}=?" for c in pk_cols)
    cleared = 0
    now = _now()
    for row in alerts:
        refs = json.loads(row["bid_refs"] or "[]")
        still_bad = []
        for bid_ref in refs:
            vals = tuple(bid_ref.split("|") if len(pk_cols) > 1 else [bid_ref])
            r = parent.execute(
                f"SELECT summary_status FROM {table} WHERE {pk_where}", vals
            ).fetchone()
            if r is None or r["summary_status"] != "done":
                still_bad.append(bid_ref)
        if not still_bad:
            parent.execute(
                "UPDATE system_alerts SET status='cleared', cleared_at=?, cleared_by=NULL "
                "WHERE id=?", (now, row["id"]),
            )
            cleared += 1
    parent.commit()
    return cleared


def auto_clear_scoring_alerts(parent: sqlite3.Connection, portal: str,
                               tool_db_path: str, pk_cols: tuple) -> int:
    """After a scoring run: auto-clear SCORING/CREDIT/KEY alerts for this portal whose
    bid_refs are all now scored. Returns number of alerts cleared."""
    alerts = parent.execute(
        "SELECT id, bid_refs FROM system_alerts "
        "WHERE portal=? AND alert_type IN ('SCORING_FAILURE','CREDIT_EXHAUSTED','INVALID_API_KEY') "
        "AND status IN ('active','retry_failed')",
        (portal,),
    ).fetchall()
    if not alerts:
        return 0

    # Check which bid_refs are still unscored in the tool DB.
    conn = sqlite3.connect(f"file:{tool_db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        pk_where = " AND ".join(f"{c}=?" for c in pk_cols)
        cleared = 0
        now = _now()
        for row in alerts:
            refs = json.loads(row["bid_refs"] or "[]")
            still_unscored = []
            for bid_id in refs:
                vals = tuple(bid_id.split("|") if len(pk_cols) > 1 else [bid_id])
                r = conn.execute(
                    f"SELECT pass1_score FROM {portal}_bids WHERE {pk_where}", vals
                ).fetchone()
                if r is None or r["pass1_score"] is None:
                    still_unscored.append(bid_id)
            if not still_unscored:
                parent.execute(
                    "UPDATE system_alerts SET status='cleared', cleared_at=?, cleared_by=NULL "
                    "WHERE id=?", (now, row["id"]),
                )
                cleared += 1
        parent.commit()
        return cleared
    finally:
        conn.close()


def purge_old_cleared(parent: sqlite3.Connection, days: int = 10) -> int:
    """Delete cleared alerts older than ``days`` days. Returns rows deleted."""
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat(timespec="seconds")
    cur = parent.execute(
        "DELETE FROM system_alerts WHERE status='cleared' AND cleared_at < ?", (cutoff,)
    )
    parent.commit()
    return cur.rowcount


def active_run(parent: sqlite3.Connection) -> sqlite3.Row | None:
    """The in-progress overall row (``finished_at IS NULL``), or None."""
    return parent.execute(
        "SELECT * FROM scrape_runs WHERE tool IS NULL AND finished_at IS NULL "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()


def active_alerts(parent: sqlite3.Connection) -> list[sqlite3.Row]:
    """Backward-compat: active+retry_failed alerts (``cleared_at IS NULL``)."""
    return parent.execute(
        "SELECT * FROM system_alerts WHERE status IN ('active','retry_failed') "
        "ORDER BY id DESC"
    ).fetchall()

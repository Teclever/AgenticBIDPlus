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
    """INSERT a sticky system_alerts row (cleared only by a human, never auto-cleared)."""
    cur = parent.execute(
        "INSERT INTO system_alerts (raised_at, run_id, reason, cleared_at, cleared_by) "
        "VALUES (?, ?, ?, NULL, NULL)",
        (_now(), run_id, reason),
    )
    parent.commit()
    return int(cur.lastrowid)


def active_run(parent: sqlite3.Connection) -> sqlite3.Row | None:
    """The in-progress overall row (``finished_at IS NULL``), or None. Powers the deploy
    active-run guard."""
    return parent.execute(
        "SELECT * FROM scrape_runs WHERE tool IS NULL AND finished_at IS NULL "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()


def active_alerts(parent: sqlite3.Connection) -> list[sqlite3.Row]:
    """Sticky, still-active alerts (``cleared_at IS NULL``)."""
    return parent.execute(
        "SELECT * FROM system_alerts WHERE cleared_at IS NULL ORDER BY id DESC"
    ).fetchall()

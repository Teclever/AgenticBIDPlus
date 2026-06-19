"""Read-only reporting module for the BidAnalysisPortal control plane.

Reads parent.db and returns plain Python data structures.  No writes,
no network calls, no Anthropic SDK — pure stdlib plus bidplus.config,
bidplus.lifecycle, and bidplus.web.mapping.

FACTS ONLY — this module never synthesises recommendations.
"""

from __future__ import annotations

import datetime
import json
import sqlite3

import bidplus.config as core
from bidplus import lifecycle
from bidplus.web import mapping

# ── connection ────────────────────────────────────────────────────────────────

def connect() -> sqlite3.Connection:
    """Open parent.db READ-ONLY.  Raises if the file does not exist."""
    path = core.PARENT_DB_PATH
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ── cycle queries ─────────────────────────────────────────────────────────────

def latest_finished_cycle(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Most recent completed overall cycle (tool IS NULL, finished_at IS NOT NULL)."""
    return conn.execute(
        "SELECT * FROM scrape_runs "
        "WHERE tool IS NULL AND finished_at IS NOT NULL "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()


def running_cycle(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """In-progress overall cycle (tool IS NULL, finished_at IS NULL), or None."""
    return conn.execute(
        "SELECT * FROM scrape_runs "
        "WHERE tool IS NULL AND finished_at IS NULL "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()


def cycle_portal_rows(conn: sqlite3.Connection, overall_id: int) -> list[sqlite3.Row]:
    """Per-portal rows (tool IS NOT NULL) that belong to the given overall cycle id.

    Uses the same id-window approach as scrape_runs_list() in web/app.py:
    per-portal rows sit between this overall row's id and the next overall
    row's id (exclusive upper bound = next-1, or a large sentinel when this
    is the most-recent cycle).
    """
    nxt = conn.execute(
        "SELECT MIN(id) FROM scrape_runs WHERE tool IS NULL AND id > ?",
        (overall_id,),
    ).fetchone()[0]
    upper = (nxt - 1) if nxt else 999_999_999
    return conn.execute(
        "SELECT * FROM scrape_runs "
        "WHERE tool IS NOT NULL AND id > ? AND id <= ? "
        "ORDER BY id ASC",
        (overall_id, upper),
    ).fetchall()


# ── per-portal inventory ──────────────────────────────────────────────────────

_CLOSING_WINDOW_DAYS = 10


def inventory(conn: sqlite3.Connection, portal: str) -> dict | None:
    """Return a summary dict for *portal*_bids, or None if the table is absent.

    Keys:
      total        — all rows
      new          — COALESCE(user_state, 'new') = 'new'
      score5_new   — pass1_score = 5 AND COALESCE(user_state, 'new') = 'new'
      closing_soon — non-CLOSED rows whose closing date falls within
                     today..today+10 days, not rejected and not auto_rejected
                     (mirrors the 'closingSoon' / cs1 logic in web/app.py stats())
    """
    table = f"{portal}_bids"
    closing_col = mapping.PORTAL_FIELDS[portal]["closing"]
    try:
        total = int(
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        )
        new = int(
            conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE COALESCE(user_state,'new')='new'"
            ).fetchone()[0]
        )
        score5_new = int(
            conn.execute(
                f"SELECT COUNT(*) FROM {table} "
                f"WHERE pass1_score=5 AND COALESCE(user_state,'new')='new'"
            ).fetchone()[0]
        )
    except sqlite3.OperationalError:
        return None

    # Closing-soon requires date parsing — mirror app.py stats() cs1 logic.
    today = datetime.date.today()
    win = today + datetime.timedelta(days=_CLOSING_WINDOW_DAYS)
    closing_soon = 0
    try:
        for r in conn.execute(
            f"SELECT user_state, auto_rejected, {closing_col} AS cdate FROM {table} "
            "WHERE COALESCE(bid_status,'') <> 'CLOSED'"
        ):
            dt = lifecycle.parse_closing(r["cdate"])
            if not (dt and today <= dt.date() <= win):
                continue
            state = r["user_state"] or "new"
            if state != "rejected" and not r["auto_rejected"]:
                closing_soon += 1
    except sqlite3.OperationalError:
        pass  # table may be absent mid-migration; totals already captured above

    return {
        "total": total,
        "new": new,
        "score5_new": score5_new,
        "closing_soon": closing_soon,
    }


# ── system alerts ─────────────────────────────────────────────────────────────

def active_alerts(conn: sqlite3.Connection) -> list[dict]:
    """Active or retry-failed system alerts, newest first.

    Returns [] if the system_alerts table does not yet exist.
    Each dict: {"alert_type", "portal", "reason", "raised_at"}.
    """
    try:
        rows = conn.execute(
            "SELECT alert_type, portal, reason, raised_at FROM system_alerts "
            "WHERE status IN ('active','retry_failed') "
            "ORDER BY id DESC"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [
        {
            "alert_type": r["alert_type"],
            "portal": r["portal"],
            "reason": r["reason"],
            "raised_at": r["raised_at"],
        }
        for r in rows
    ]


# ── summary text helper ───────────────────────────────────────────────────────

def _summary_text(raw: str | None) -> str:
    """Extract a human-readable facts-only blurb from a stored summary_json string.

    Primary text: project_description, falling back to technical_scope.
    Fact notes (joined by ' · '): single_vendor_name, has_restrictive_eligibility,
    total_value.  Combined text is capped at 3000 characters.
    Returns "" for falsy, non-dict, or unparseable input.
    """
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""

    main = (data.get("project_description") or data.get("technical_scope") or "").strip()

    notes: list[str] = []
    if data.get("single_vendor") and data.get("single_vendor_name"):
        notes.append(f"Single vendor: {data['single_vendor_name']}")
    if data.get("has_restrictive_eligibility"):
        notes.append("Restrictive eligibility")
    if data.get("total_value"):
        notes.append(f"Value: {data['total_value']}")

    parts = [main] if main else []
    if notes:
        parts.append(" · ".join(notes))
    combined = "\n".join(parts)
    return combined[:3000]


# ── cross-portal bid list ─────────────────────────────────────────────────────

def bid_list(
    conn: sqlite3.Connection,
    portals: tuple[str, ...] | list[str] | None = None,
    since: str | None = None,
) -> list[dict]:
    """Return active (non-CLOSED, non-auto_rejected) bids across all portals.

    Default portals: bidplus.config.PORTALS. When ``since`` (an ISO timestamp) is
    given, only rows UPSERTED at/after it are returned — i.e. ``last_synced_at >= since``,
    which the merge stamps only on inserted/changed rows (used for the per-rerun delta tab).

    Each dict:
      portal   — portal key (hal / halc / isro / gem)
      bid_id   — human-facing id from mapping.bid_id_display()
      title    — from PORTAL_FIELDS[portal]["title"] column
      org      — from PORTAL_FIELDS[portal]["buyer"] column
      score    — pass1_score (int or None)
      summary  — plain-text facts from _summary_text(summary_json)
      closing  — raw closing-date string from the portal's closing column

    Sorted by score DESC (None last), then portal.
    """
    if portals is None:
        portals = core.PORTALS

    results: list[dict] = []
    for portal in portals:
        table = f"{portal}_bids"
        f = mapping.PORTAL_FIELDS[portal]
        title_col = f["title"]
        buyer_col = f["buyer"]
        closing_col = f["closing"]

        # SELECT everything so bid_id_display() has all PK cols.
        where = "COALESCE(bid_status,'') <> 'CLOSED' AND COALESCE(auto_rejected,0) = 0"
        params: list = []
        if since:
            where += " AND last_synced_at >= ?"
            params.append(since)
        try:
            rows = conn.execute(f"SELECT * FROM {table} WHERE {where}", params).fetchall()
        except sqlite3.OperationalError:
            continue  # table absent — skip portal silently

        for r in rows:
            row_dict = dict(r)
            results.append({
                "portal": portal,
                "bid_id": mapping.bid_id_display(row_dict, portal),
                "title": row_dict.get(title_col) if title_col else None,
                "org": row_dict.get(buyer_col) if buyer_col else None,
                "score": row_dict.get("pass1_score"),
                "summary": _summary_text(row_dict.get("summary_json")),
                "closing": row_dict.get(closing_col) if closing_col else None,
            })

    results.sort(key=lambda d: (d["score"] is None, -(d["score"] or 0), d["portal"]))
    return results

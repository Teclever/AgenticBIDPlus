"""Tiered gate (S4) — bucket parent-DB bids into work queues. COMPUTE ONLY.

The gate never calls Sonnet and never fetches a document. It reads each ``{portal}_bids``
table and buckets bids so S6 knows what to do overnight:

- **auto_summarize** (Pass 2 now): ``pass1_score = 5`` AND ``docs_summarized = 0`` AND
  ``summary_status IS NULL`` — already-summarized and previously-``failed`` bids are
  excluded so they are not re-burned every night.
- **local_extract** (docs + text extraction, NO summary): ``pass1_score = 4`` AND
  ``local_extracted = 0``.
- **on_demand**: ``pass1_score <= 3`` — no automatic work (web-app "Retrieve information").

**Exclusions (apply to every bucket):** ``bid_status = 'CLOSED'`` (terminal) and
``pass1_method = 'keyword'`` (the soft-flagged pre-Pass-1 eliminations, score 0) are
excluded from all queues.

Because the buckets are pure queries over the merged parent DB, there is no stored queue
table — S6 recomputes the gate when it runs. Score 5 is the only bucket that triggers an
automatic Sonnet call; everything else is user-triggered (decision #1).
"""

from __future__ import annotations

import sqlite3

import bidplus.config as config

# PK columns per portal table (for returning sample work-queue ids).
_PK = {
    "hal": ("tender_number", "line_number"),
    "isro": ("tender_id",),
    "gem": ("bid_number",),
}

# A bid is out of every queue if it is CLOSED or was keyword-eliminated. COALESCE keeps
# the predicate NULL-safe: pass1_method is NULL until S5 writes it, and `x = 'keyword'`
# on a NULL yields NULL (not FALSE), which would otherwise make `NOT (...)` filter out
# every row under SQLite's three-valued logic.
_EXCLUDED = (
    "(COALESCE(bid_status, '') = 'CLOSED' "
    "OR COALESCE(pass1_method, '') = 'keyword')"
)
_NOT_EXCLUDED = f"NOT {_EXCLUDED}"


def _count(conn: sqlite3.Connection, table: str, where: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0])


def _sample_pks(conn: sqlite3.Connection, portal: str, table: str, where: str,
                limit: int = 5) -> list[str]:
    pk = _PK[portal]
    rows = conn.execute(
        f"SELECT {', '.join(pk)} FROM {table} WHERE {where} LIMIT {limit}"
    ).fetchall()
    return ["|".join(str(v) for v in r) for r in rows]


def gate_portal(conn: sqlite3.Connection, portal: str) -> dict:
    """Bucket one portal's parent table. Returns counts + a small pk sample per queue."""
    table = f"{portal}_bids"
    auto_where = (
        f"pass1_score = {config.SCORE_AUTO_SUMMARIZE} AND docs_summarized = 0 "
        f"AND summary_status IS NULL AND {_NOT_EXCLUDED}"
    )
    local_where = (
        f"pass1_score = {config.SCORE_LOCAL_EXTRACT} AND local_extracted = 0 "
        f"AND {_NOT_EXCLUDED}"
    )
    return {
        "portal": portal,
        "auto_summarize": _count(conn, table, auto_where),
        "local_extract": _count(conn, table, local_where),
        "on_demand": _count(conn, table, f"pass1_score <= 3 AND {_NOT_EXCLUDED}"),
        "excluded_closed": _count(conn, table, "bid_status = 'CLOSED'"),
        "excluded_keyword": _count(
            conn, table, "pass1_method = 'keyword' AND COALESCE(bid_status,'') <> 'CLOSED'"
        ),
        "auto_summarize_pks": _sample_pks(conn, portal, table, auto_where),
        "local_extract_pks": _sample_pks(conn, portal, table, local_where),
    }


def work_pks(conn: sqlite3.Connection, portal: str) -> dict:
    """The FULL (unsampled) auto_summarize (score 5) + local_extract (score 4) work queues
    for one portal — what the nightly Pass-2 phase actually iterates. Mirrors the gate_portal
    predicates exactly so reporting and execution can never diverge."""
    table = f"{portal}_bids"
    auto_where = (
        f"pass1_score = {config.SCORE_AUTO_SUMMARIZE} AND docs_summarized = 0 "
        f"AND summary_status IS NULL AND {_NOT_EXCLUDED}"
    )
    local_where = (
        f"pass1_score = {config.SCORE_LOCAL_EXTRACT} AND local_extracted = 0 "
        f"AND {_NOT_EXCLUDED}"
    )
    return {
        "auto_summarize": _sample_pks(conn, portal, table, auto_where, limit=-1),
        "local_extract": _sample_pks(conn, portal, table, local_where, limit=-1),
    }


def tiered_gate(conn: sqlite3.Connection,
                portals: tuple[str, ...] | None = None) -> dict:
    """Bucket all portals. Returns ``{per_portal: {...}, totals: {...}}``."""
    portals = portals or config.PORTALS
    per_portal = {p: gate_portal(conn, p) for p in portals}
    keys = ("auto_summarize", "local_extract", "on_demand",
            "excluded_closed", "excluded_keyword")
    totals = {k: sum(per_portal[p][k] for p in portals) for k in keys}
    return {"per_portal": per_portal, "totals": totals}

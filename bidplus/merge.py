"""Parent-DB merge (S3) — gap-aware full-reconciliation upsert.

Each tool keeps its own ``bids.db`` (the operational store). This module merges each
tool DB into the single ``parent.db`` that the web app will later read — **one table
per portal** (``hal_bids`` / ``isro_bids`` / ``gem_bids``), each mirroring its tool
schema plus a parent-owned **overlay** block.

Invariants (AGENTS.md / plan §4):
- The merge is **always UPSERT**, never blind-insert and never delete (lifecycle/CLOSED
  is a later slice; a row that vanishes from the tool is retained).
- It mirrors **tool-owned** columns only. It **NEVER overwrites an overlay column**
  (AI-derived ``local_*``/``summary_*``/``has_restrictive_eligibility`` or human
  ``user_state``/``disposed_*``/``human_disposition``/``human_reason``) — overlay is
  parent-owned and written once by S5/S6/the web app.
- An **EXTENDED** bid updates only the mirrored tool fields (``bid_status`` /
  ``extension_count`` / the closing-date column); it is **not** re-summarized.
- The per-row UPDATE is **conditional on a real value difference**, so re-running the
  merge with no tool changes is a true no-op (idempotent) — even ``last_synced_at`` is
  left untouched on unchanged rows.

The parent table shape is derived from the tool schema (so per-portal column-name
differences — HAL ``closing_date`` vs ISRO ``bid_closing_date`` vs GeM ``end_date`` —
need no special-casing), minus a denylist of legacy columns the scoring redesign drops,
plus the S5 scoring columns and the overlay block. Schema changes are applied as
**additive ``ALTER TABLE ADD COLUMN``** so a later slice's new column lands without a
rebuild.
"""

from __future__ import annotations

import datetime
import sqlite3

import bidplus.config as config
from bidplus.adapters.gem import GeMAdapter
from bidplus.adapters.hal import HALAdapter
from bidplus.adapters.isro import ISROAdapter

_ADAPTERS = {"hal": HALAdapter, "isro": ISROAdapter, "gem": GeMAdapter}
_SOURCE_TABLE = {"hal": "tenders", "isro": "bids", "gem": "bids"}

# Legacy tool columns the scoring redesign DROPS — not mirrored into the parent:
# the second-scoring Pass 2 (deleted), Excel/export flags, the GeM exclusion pre-filter
# (superseded by the S5 eliminator), and the tools' legacy Pass-1 human override.
_DENYLIST = {
    "pass2_score", "pass2_confidence", "pass2_domain", "pass2_rationale",
    "pass2_gaps", "pass2_recommendation", "run_pass2", "pass2_attempted",
    "human_override_score", "human_override_reason", "pass1_exported",
    "exclusion_matched",
}

# Scoring columns the centralized module (S5) will add to each tool DB. Declared on the
# parent now (defaulted) so the merge picks them up automatically once they exist
# tool-side — no parent migration needed at S5. Mirror (tool-owned), NOT overlay.
_EXTRA_MIRROR = [
    ("pass1_method", "TEXT", None),
    ("pass1_eliminated_by", "TEXT", None),
    ("auto_rejected", "INTEGER", "0"),
]

# Parent-owned OVERLAY block (plan §7). Written once by S5/S6 + the web app; the merge
# NEVER writes these. AI-derived first, then human.
_OVERLAY = [
    ("local_extracted", "INTEGER", "0"),
    ("local_extract_json", "TEXT", None),
    ("docs_summarized", "INTEGER", "0"),
    ("summary_status", "TEXT", None),
    ("summary_json", "TEXT", None),
    ("summary_model", "TEXT", None),
    ("summary_generated_at", "TEXT", None),
    ("summary_coverage", "TEXT", "'full'"),
    ("has_restrictive_eligibility", "INTEGER", "0"),
    ("user_state", "TEXT", "'new'"),
    ("human_disposition", "TEXT", None),
    ("human_reason", "TEXT", None),
    ("disposed_by", "INTEGER", None),
    ("disposed_at", "TEXT", None),
]
_OVERLAY_COLS = {name for name, _, _ in _OVERLAY}


# ── schema introspection ─────────────────────────────────────────────────────────

def _table_info(conn: sqlite3.Connection, table: str) -> list:
    return conn.execute(f"PRAGMA table_info({table})").fetchall()


def _tool_columns(tool: sqlite3.Connection, table: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Return (``[(name, type), …]``, ``[pk cols in order]``) for the tool table."""
    info = _table_info(tool, table)  # cid, name, type, notnull, dflt, pk
    cols = [(r[1], r[2] or "TEXT") for r in info]
    pk = [r[1] for r in sorted((r for r in info if r[5] > 0), key=lambda r: r[5])]
    return cols, pk


def _mirror_specs(tool_cols: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Tool columns the parent mirrors (denylist + overlay-name filtered), in order."""
    return [
        (n, t) for (n, t) in tool_cols
        if n not in _DENYLIST and n not in _OVERLAY_COLS
    ]


def _desired_columns(tool_cols: list[tuple[str, str]]) -> list[tuple[str, str, str | None]]:
    """Ordered ``(name, type, default)`` for the parent table: mirrored tool cols, then
    the S5 scoring cols, then the overlay block, then ``last_synced_at``. PK is added
    separately by :func:`_ensure_table`."""
    seen: set[str] = set()
    out: list[tuple[str, str, str | None]] = []
    for n, t in _mirror_specs(tool_cols):
        out.append((n, t, None)); seen.add(n)
    for n, t, d in _EXTRA_MIRROR + _OVERLAY:
        if n not in seen:
            out.append((n, t, d)); seen.add(n)
    out.append(("last_synced_at", "TEXT", None))
    return out


def _col_ddl(name: str, type_: str, default: str | None) -> str:
    return f"{name} {type_}" + (f" DEFAULT {default}" if default is not None else "")


# ── connections + schema creation ────────────────────────────────────────────────

def connect_parent() -> sqlite3.Connection:
    """Open (creating if needed) ``parent.db`` in WAL mode under the runtime dir."""
    config.PARENT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.PARENT_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_shared(parent: sqlite3.Connection) -> None:
    """Create the shared ``users`` / ``scrape_runs`` / ``system_alerts`` tables (S3 owns
    the first two; ``scrape_runs``/``system_alerts`` rows are written at S4)."""
    parent.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        " id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,"
        " password_hash TEXT NOT NULL, created_at TEXT)"
    )
    parent.execute(
        "CREATE TABLE IF NOT EXISTS scrape_runs ("
        " id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT, tool TEXT,"
        " status TEXT, new_count INTEGER, updated_count INTEGER, closed_count INTEGER,"
        " scored_count INTEGER, local_extracted_count INTEGER, summarized_count INTEGER,"
        " summary_failed_count INTEGER, error_summary TEXT, stage_timings_json TEXT)"
    )
    parent.execute(
        "CREATE TABLE IF NOT EXISTS system_alerts ("
        " id INTEGER PRIMARY KEY, raised_at TEXT, run_id INTEGER, reason TEXT,"
        " cleared_at TEXT, cleared_by INTEGER)"
    )
    # Additive migration: add typed-alert columns if absent (safe on existing DBs).
    _have = {r[1] for r in parent.execute("PRAGMA table_info(system_alerts)")}
    for _col, _decl in (
        ("alert_type",      "TEXT DEFAULT 'CYCLE_FAILED'"),
        ("portal",          "TEXT"),
        ("bid_refs",        "TEXT"),           # JSON array of source_pks
        ("status",          "TEXT DEFAULT 'active'"),
        ("retry_count",     "INTEGER DEFAULT 0"),
        ("last_retry_at",   "TEXT"),
        ("last_retry_by",   "INTEGER"),
        ("last_retry_error","TEXT"),
    ):
        if _col not in _have:
            parent.execute(f"ALTER TABLE system_alerts ADD COLUMN {_col} {_decl}")
    # Back-fill status for rows written before this migration (cleared_at set → cleared).
    parent.execute(
        "UPDATE system_alerts SET status='cleared' "
        "WHERE cleared_at IS NOT NULL AND status='active'"
    )


def _ensure_table(parent: sqlite3.Connection, portal: str,
                  tool_cols: list[tuple[str, str]], pk: list[str]) -> str:
    """Create ``{portal}_bids`` if absent; otherwise additively add any missing column."""
    table = f"{portal}_bids"
    desired = _desired_columns(tool_cols)
    existing = {r[1] for r in _table_info(parent, table)}
    if not existing:
        coldefs = ",\n  ".join(_col_ddl(n, t, d) for n, t, d in desired)
        parent.execute(
            f"CREATE TABLE {table} (\n  {coldefs},\n  PRIMARY KEY ({', '.join(pk)})\n)"
        )
    else:
        for n, t, d in desired:
            if n not in existing:
                parent.execute(f"ALTER TABLE {table} ADD COLUMN {_col_ddl(n, t, d)}")
    return table


# ── the merge ────────────────────────────────────────────────────────────────────

def merge_portal(portal: str, parent: sqlite3.Connection | None = None) -> dict:
    """Upsert one tool ``bids.db`` into its parent table. Returns count dict."""
    src_table = _SOURCE_TABLE[portal]
    tool_path = _ADAPTERS[portal]().tool_db_path()

    own_parent = parent is None
    if own_parent:
        parent = connect_parent()
    tool = sqlite3.connect(f"file:{tool_path}?mode=ro", uri=True)
    tool.row_factory = sqlite3.Row
    try:
        ensure_shared(parent)
        tool_cols, pk = _tool_columns(tool, src_table)
        if not pk:
            raise RuntimeError(f"{portal}: tool table {src_table!r} has no primary key")
        ptable = _ensure_table(parent, portal, tool_cols, pk)

        write_cols = [n for n, _ in _mirror_specs(tool_cols)]
        pk_where = " AND ".join(f"{c}=?" for c in pk)
        now = datetime.datetime.now().isoformat(timespec="seconds")

        inserted = updated = unchanged = 0
        cur = parent.cursor()
        for r in tool.execute(f"SELECT * FROM {src_table}").fetchall():
            pk_vals = [r[c] for c in pk]
            existing = cur.execute(
                f"SELECT {', '.join(write_cols)} FROM {ptable} WHERE {pk_where}", pk_vals
            ).fetchone()
            if existing is None:
                cols = write_cols + ["last_synced_at"]
                vals = [r[c] for c in write_cols] + [now]
                cur.execute(
                    f"INSERT INTO {ptable} ({', '.join(cols)}) "
                    f"VALUES ({', '.join('?' * len(cols))})",
                    vals,
                )
                inserted += 1
            elif any(existing[i] != r[write_cols[i]] for i in range(len(write_cols))):
                set_clause = ", ".join(f"{c}=?" for c in write_cols) + ", last_synced_at=?"
                cur.execute(
                    f"UPDATE {ptable} SET {set_clause} WHERE {pk_where}",
                    [r[c] for c in write_cols] + [now] + pk_vals,
                )
                updated += 1
            else:
                unchanged += 1
        parent.commit()
        return {
            "portal": portal, "tool_rows": inserted + updated + unchanged,
            "inserted": inserted, "updated": updated, "unchanged": unchanged,
        }
    finally:
        tool.close()
        if own_parent:
            parent.close()


def merge_all(portals: tuple[str, ...] | list[str] | None = None) -> list[dict]:
    """Merge each portal sequentially into the one parent DB. Default: all PORTALS."""
    portals = tuple(portals) if portals else config.PORTALS
    parent = connect_parent()
    try:
        ensure_shared(parent)
        return [merge_portal(p, parent=parent) for p in portals]
    finally:
        parent.close()


# ── validation (DONE-WHEN: parent mirrors the tool for all synced fields) ──────────

def compare_portal(portal: str, parent: sqlite3.Connection | None = None) -> dict:
    """Compare ``{portal}_bids`` against the tool DB over the mirrored columns. Returns
    ``{tool_rows, parent_rows, missing_in_parent, value_mismatches, sample}``."""
    src_table = _SOURCE_TABLE[portal]
    tool_path = _ADAPTERS[portal]().tool_db_path()
    own_parent = parent is None
    if own_parent:
        parent = connect_parent()
    tool = sqlite3.connect(f"file:{tool_path}?mode=ro", uri=True)
    tool.row_factory = sqlite3.Row
    try:
        ptable = f"{portal}_bids"
        tool_cols, pk = _tool_columns(tool, src_table)
        write_cols = [n for n, _ in _mirror_specs(tool_cols)]
        pk_where = " AND ".join(f"{c}=?" for c in pk)
        cur = parent.cursor()
        parent_rows = cur.execute(f"SELECT COUNT(*) FROM {ptable}").fetchone()[0]
        missing = mism = 0
        sample: list[str] = []
        tool_rows = 0
        for r in tool.execute(f"SELECT * FROM {src_table}").fetchall():
            tool_rows += 1
            pk_vals = [r[c] for c in pk]
            prow = cur.execute(
                f"SELECT {', '.join(write_cols)} FROM {ptable} WHERE {pk_where}", pk_vals
            ).fetchone()
            if prow is None:
                missing += 1
                if len(sample) < 5:
                    sample.append(f"missing pk={pk_vals}")
            elif any(prow[i] != r[write_cols[i]] for i in range(len(write_cols))):
                mism += 1
                if len(sample) < 5:
                    bad = [write_cols[i] for i in range(len(write_cols))
                           if prow[i] != r[write_cols[i]]]
                    sample.append(f"pk={pk_vals} differs on {bad}")
        return {
            "portal": portal, "tool_rows": tool_rows, "parent_rows": parent_rows,
            "missing_in_parent": missing, "value_mismatches": mism, "sample": sample,
        }
    finally:
        tool.close()
        if own_parent:
            parent.close()

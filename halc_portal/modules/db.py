"""SQLite persistence layer — the single source of truth.

Owns the `bids` schema, idempotent upserts, tender lifecycle transitions
(NEW/ACTIVE/EXTENDED/CLOSED), the Pass 2 candidate query, and Excel-ingest
bookkeeping. No other module issues SQL. Key invariants:

- `tender_id` is PRIMARY KEY — always UPSERT, never blind INSERT.
- Scores and human columns are never overwritten by a re-scrape.
- `pass2_attempted` is monotonic; `CLOSED` is terminal.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Any

from config import DB_PATH, PASS2_THRESHOLD


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _conn()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS bids (
                tender_id                TEXT PRIMARY KEY,
                ref_no                   TEXT,
                category                 TEXT,
                center_name              TEXT,
                tender_description       TEXT,
                bid_closing_date         TEXT,
                bid_opening_date         TEXT,
                document_url             TEXT,
                detail_url               TEXT,
                corrigendum_url          TEXT,
                detail_text              TEXT,
                doc_links_json           TEXT,
                pass1_score              INTEGER,
                pass1_confidence         TEXT,
                pass1_domain             TEXT,
                pass1_rationale          TEXT,
                pass1_gaps               TEXT,
                pass2_score              INTEGER,
                pass2_confidence         TEXT,
                pass2_domain             TEXT,
                pass2_rationale          TEXT,
                pass2_gaps               TEXT,
                pass2_recommendation     TEXT,
                human_override_score     INTEGER,
                human_override_reason    TEXT,
                run_pass2                INTEGER DEFAULT 0,
                pass2_attempted          INTEGER DEFAULT 0,
                bid_status               TEXT DEFAULT 'NEW',
                previous_closing_date    TEXT,
                extension_count          INTEGER DEFAULT 0,
                first_seen_date          TEXT,
                last_seen_at             TEXT,
                last_updated_date        TEXT,
                pass1_exported           INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS excel_log (
                filename            TEXT PRIMARY KEY,
                ingested_date       TEXT,
                overrides_found     INTEGER,
                overrides_applied   INTEGER
            );
            """
        )
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(bids)").fetchall()}
    additions = [
        ("previous_closing_date", "TEXT"),
        ("extension_count", "INTEGER DEFAULT 0"),
        ("ref_no", "TEXT"),
        ("category", "TEXT"),
    ]
    for col, dtype in additions:
        if col not in existing:
            conn.execute(f"ALTER TABLE bids ADD COLUMN {col} {dtype}")


def upsert_raw_bid(bid: dict[str, Any]) -> str:
    now = dt.datetime.now().isoformat(timespec="seconds")
    today = dt.date.today().isoformat()
    tender_id = bid["tender_id"]
    conn = _conn()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO bids (tender_id, bid_status, first_seen_date, last_seen_at) VALUES (?, 'NEW', ?, ?)",
            (tender_id, today, now),
        )
        inserted = cur.rowcount == 1
        if not inserted:
            row = conn.execute(
                "SELECT bid_status, bid_closing_date, previous_closing_date, extension_count FROM bids WHERE tender_id=?",
                (tender_id,),
            ).fetchone()
            status = row["bid_status"]
            old_close = row["bid_closing_date"]
            new_close = bid.get("bid_closing_date")
            extension_count = int(row["extension_count"] or 0)
            previous_closing = row["previous_closing_date"]

            if status != "CLOSED" and old_close and new_close and old_close != new_close:
                status = "EXTENDED"
                previous_closing = old_close
                extension_count += 1
            elif status != "CLOSED":
                status = "ACTIVE"
            conn.execute(
                "UPDATE bids SET bid_status=?, previous_closing_date=?, extension_count=?, last_seen_at=? WHERE tender_id=?",
                (status, previous_closing, extension_count, now, tender_id),
            )

        # detail_text / doc_links_json are intentionally NOT refreshed here: a
        # bare listing scrape carries no such data, and overwriting them would
        # wipe previously enriched text. detail_text is set by the scoped
        # enrichment step; document links are resolved live at Pass 2 time.
        fields = [
            "ref_no",
            "category",
            "center_name",
            "tender_description",
            "bid_closing_date",
            "bid_opening_date",
            "document_url",
            "detail_url",
            "corrigendum_url",
        ]
        updates = {f: bid.get(f) for f in fields}
        set_clause = ", ".join(f"{k}=?" for k in updates.keys())
        conn.execute(
            f"UPDATE bids SET {set_clause}, last_updated_date=? WHERE tender_id=?",
            [*updates.values(), today, tender_id],
        )
        conn.commit()
        return "inserted" if inserted else "updated"
    finally:
        conn.close()


def sweep_closed_bids() -> int:
    now = dt.datetime.now()
    today_iso = now.date().isoformat()
    conn = _conn()
    updated = 0
    try:
        rows = conn.execute(
            "SELECT tender_id, bid_closing_date, bid_status FROM bids WHERE bid_closing_date IS NOT NULL"
        ).fetchall()
        for row in rows:
            if row["bid_status"] == "CLOSED":
                continue
            parsed = _parse_portal_dt(row["bid_closing_date"])
            if parsed and parsed < now:
                conn.execute(
                    "UPDATE bids SET bid_status='CLOSED', last_updated_date=? WHERE tender_id=?",
                    (today_iso, row["tender_id"]),
                )
                updated += 1
        conn.commit()
        return updated
    finally:
        conn.close()


def update_detail_text(tender_id: str, detail_text: str) -> None:
    conn = _conn()
    try:
        conn.execute(
            "UPDATE bids SET detail_text=?, last_updated_date=? WHERE tender_id=?",
            (detail_text, dt.date.today().isoformat(), tender_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_unscored_bids() -> list[sqlite3.Row]:
    conn = _conn()
    try:
        return conn.execute(
            """
            SELECT * FROM bids
            WHERE pass1_score IS NULL
              AND bid_status != 'CLOSED'
            ORDER BY tender_id
            """
        ).fetchall()
    finally:
        conn.close()


def update_pass1_score(tender_id: str, fields: dict[str, Any]) -> None:
    conn = _conn()
    try:
        conn.execute(
            """
            UPDATE bids
            SET pass1_score=?, pass1_confidence=?, pass1_domain=?, pass1_rationale=?, pass1_gaps=?
            WHERE tender_id=?
            """,
            (
                fields.get("pass1_score"),
                fields.get("pass1_confidence"),
                fields.get("pass1_domain"),
                fields.get("pass1_rationale"),
                fields.get("pass1_gaps"),
                tender_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def query_pass2_candidates() -> list[sqlite3.Row]:
    conn = _conn()
    try:
        return conn.execute(
            """
            SELECT * FROM bids
            WHERE bid_status != 'CLOSED'
              AND pass2_score IS NULL
              AND pass2_attempted = 0
              AND (
                    run_pass2 = 1
                    OR (pass1_score >= ? AND COALESCE(run_pass2, 0) != -1)
                  )
            ORDER BY pass1_score DESC, tender_id
            """,
            (PASS2_THRESHOLD,),
        ).fetchall()
    finally:
        conn.close()


def set_pass2_attempted(tender_id: str) -> None:
    conn = _conn()
    try:
        conn.execute("UPDATE bids SET pass2_attempted=1 WHERE tender_id=?", (tender_id,))
        conn.commit()
    finally:
        conn.close()


def update_pass2_score(tender_id: str, fields: dict[str, Any]) -> None:
    conn = _conn()
    try:
        conn.execute(
            """
            UPDATE bids
            SET pass2_score=?, pass2_confidence=?, pass2_domain=?, pass2_rationale=?, pass2_gaps=?, pass2_recommendation=?
            WHERE tender_id=?
            """,
            (
                fields.get("pass2_score"),
                fields.get("pass2_confidence"),
                fields.get("pass2_domain"),
                fields.get("pass2_rationale"),
                fields.get("pass2_gaps"),
                fields.get("pass2_recommendation"),
                tender_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_all_bids() -> list[sqlite3.Row]:
    conn = _conn()
    try:
        return conn.execute("SELECT * FROM bids ORDER BY tender_id").fetchall()
    finally:
        conn.close()


def get_unexported_pass1_bids() -> list[sqlite3.Row]:
    conn = _conn()
    try:
        return conn.execute(
            "SELECT * FROM bids WHERE pass1_score IS NOT NULL AND pass1_exported=0 ORDER BY tender_id"
        ).fetchall()
    finally:
        conn.close()


def mark_pass1_exported(tender_ids: list[str]) -> None:
    if not tender_ids:
        return
    conn = _conn()
    try:
        conn.executemany("UPDATE bids SET pass1_exported=1 WHERE tender_id=?", [(x,) for x in tender_ids])
        conn.commit()
    finally:
        conn.close()


def already_ingested(filename: str) -> bool:
    conn = _conn()
    try:
        row = conn.execute("SELECT 1 FROM excel_log WHERE filename=?", (filename,)).fetchone()
        return row is not None
    finally:
        conn.close()


def log_ingest(filename: str, overrides_found: int, overrides_applied: int) -> None:
    conn = _conn()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO excel_log(filename, ingested_date, overrides_found, overrides_applied)
            VALUES (?, ?, ?, ?)
            """,
            (filename, dt.datetime.now().isoformat(timespec="seconds"), overrides_found, overrides_applied),
        )
        conn.commit()
    finally:
        conn.close()


def update_human_inputs(tender_id: str, run_pass2: int | None, override_score: int | None, override_reason: str | None) -> None:
    conn = _conn()
    try:
        existing = conn.execute("SELECT run_pass2 FROM bids WHERE tender_id=?", (tender_id,)).fetchone()
        if not existing:
            return
        run_val = existing["run_pass2"] if run_pass2 is None else run_pass2
        conn.execute(
            """
            UPDATE bids
            SET run_pass2=?, human_override_score=COALESCE(?, human_override_score), human_override_reason=COALESCE(?, human_override_reason)
            WHERE tender_id=?
            """,
            (run_val, override_score, override_reason, tender_id),
        )
        conn.commit()
    finally:
        conn.close()


def _parse_portal_dt(raw: str | None) -> dt.datetime | None:
    if not raw:
        return None
    for fmt in ("%d-%B-%Y %H:%M", "%d-%b-%Y %H:%M", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    return None

import sqlite3
import datetime
from typing import Any

from config import DB_PATH, PASS2_THRESHOLD

# Fields that upsert_tender must never overwrite
_PRESERVED = frozenset({
    "tender_number", "line_number",
    "pass1_score", "pass1_confidence", "pass1_domain", "pass1_rationale", "pass1_gaps",
    "pass1_recommendation", "pass1_matching_tech",
    "pass2_score", "pass2_confidence", "pass2_domain", "pass2_rationale",
    "pass2_gaps", "pass2_recommendation",
    "human_override_score", "human_override_reason",
    "run_pass2", "pass2_attempted",
    "bid_status", "previous_closing_date", "extension_count",
    "first_seen_date", "last_seen_at", "pass1_exported",
})


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(tenders)").fetchall()}
    additions = [
        ("tender_cover",      "TEXT"),
        ("announcement_date", "TEXT"),
        ("tender_type",       "TEXT"),
        ("submission_type",   "TEXT"),
        ("tender_for",        "TEXT"),
        ("directory_id",      "INTEGER"),
        ("issue_date_from",   "TEXT"),
        ("issue_date_to",     "TEXT"),
        ("pass1_recommendation", "TEXT"),
        ("pass1_matching_tech",  "TEXT"),
    ]
    for col, dtype in additions:
        if col not in existing:
            conn.execute(f"ALTER TABLE tenders ADD COLUMN {col} {dtype}")
    conn.commit()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tenders (
                tender_number           TEXT NOT NULL,
                line_number             TEXT NOT NULL,
                buyer                   TEXT,
                tender_description      TEXT,
                estimated_cost          TEXT,
                form_fee                TEXT,
                emd_listing             TEXT,
                tender_stage            TEXT,
                tender_region           TEXT,
                bidder_type             TEXT,
                closing_date            TEXT,
                tender_cover            TEXT,
                announcement_date       TEXT,
                tender_type             TEXT,
                submission_type         TEXT,
                tender_for              TEXT,
                directory_id            INTEGER,
                issue_date_from         TEXT,
                issue_date_to           TEXT,
                opening_date            TEXT,
                cost_open_date          TEXT,
                tender_mode             TEXT,
                validity_of_bid         TEXT,
                contact_email           TEXT,
                contact_person          TEXT,
                qualification_criteria  TEXT,
                additional_notes        TEXT,
                emd_amount              TEXT,
                contract_value          TEXT,
                pass1_score             INTEGER,
                pass1_confidence        TEXT,
                pass1_domain            TEXT,
                pass1_rationale         TEXT,
                pass1_gaps              TEXT,
                pass2_score             INTEGER,
                pass2_confidence        TEXT,
                pass2_domain            TEXT,
                pass2_rationale         TEXT,
                pass2_gaps              TEXT,
                pass2_recommendation    TEXT,
                human_override_score    INTEGER,
                human_override_reason   TEXT,
                run_pass2               INTEGER DEFAULT 0,
                pass2_attempted         INTEGER DEFAULT 0,
                bid_status              TEXT DEFAULT 'NEW',
                previous_closing_date   TEXT,
                extension_count         INTEGER DEFAULT 0,
                first_seen_date         TEXT,
                last_seen_at            TEXT,
                last_updated_date       TEXT,
                pass1_exported          INTEGER DEFAULT 0,
                PRIMARY KEY (tender_number, line_number)
            );

            CREATE TABLE IF NOT EXISTS excel_log (
                filename            TEXT PRIMARY KEY,
                ingested_date       TEXT,
                overrides_found     INTEGER,
                overrides_applied   INTEGER
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                tender_number       TEXT,
                line_number         TEXT,
                original_score      INTEGER,
                corrected_score     INTEGER,
                reason              TEXT,
                promoted_to_rule    INTEGER DEFAULT 0,
                created_date        TEXT
            );

            CREATE TABLE IF NOT EXISTS few_shot_examples (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                tender_title    TEXT,
                correct_score   INTEGER,
                reason          TEXT,
                created_date    TEXT
            );
        """)
        _migrate(conn)
    finally:
        conn.close()


def upsert_raw_tender(tender: dict) -> None:
    """Insert or update listing fields. Handles NEW/ACTIVE/EXTENDED lifecycle."""
    today = datetime.date.today().isoformat()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    tn = tender["tender_number"]
    ln = tender["line_number"]

    conn = _get_conn()
    try:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO tenders "
            "(tender_number, line_number, bid_status, first_seen_date, last_seen_at, extension_count) "
            "VALUES (?, ?, 'NEW', ?, ?, 0)",
            (tn, ln, today, now),
        )
        is_new = cursor.rowcount == 1

        if not is_new:
            existing = conn.execute(
                "SELECT bid_status, closing_date, extension_count, previous_closing_date "
                "FROM tenders WHERE tender_number=? AND line_number=?",
                (tn, ln),
            ).fetchone()

            new_closing = tender.get("closing_date")
            old_closing = existing["closing_date"]

            if (
                existing["bid_status"] not in ("CLOSED",)
                and new_closing
                and old_closing
                and new_closing != old_closing
            ):
                new_status = "EXTENDED"
                prev_closing = old_closing
                ext_count = (existing["extension_count"] or 0) + 1
            else:
                new_status = "ACTIVE" if existing["bid_status"] != "CLOSED" else "CLOSED"
                prev_closing = existing["previous_closing_date"]
                ext_count = existing["extension_count"] or 0

            conn.execute(
                "UPDATE tenders SET bid_status=?, previous_closing_date=?, extension_count=?, "
                "last_seen_at=? WHERE tender_number=? AND line_number=?",
                (new_status, prev_closing, ext_count, now, tn, ln),
            )

        # Always refresh listing fields from the latest scrape
        listing_fields = [
            "buyer", "tender_description", "estimated_cost", "form_fee", "emd_listing",
            "tender_stage", "tender_region", "bidder_type", "closing_date",
            "tender_cover", "announcement_date", "tender_type", "submission_type",
            "tender_for", "directory_id", "issue_date_from", "issue_date_to",
        ]
        updates: dict[str, Any] = {f: tender[f] for f in listing_fields if f in tender}
        if updates:
            set_clause = ", ".join(f"{k}=?" for k in updates)
            conn.execute(
                f"UPDATE tenders SET {set_clause}, last_updated_date=? "
                "WHERE tender_number=? AND line_number=?",
                [*updates.values(), today, tn, ln],
            )

        conn.commit()
    finally:
        conn.close()


def upsert_tender(tender: dict) -> None:
    """Update portal fields (listing + detail) without touching scoring, human, or lifecycle fields."""
    today = datetime.date.today().isoformat()
    tn = tender["tender_number"]
    ln = tender["line_number"]

    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO tenders (tender_number, line_number) VALUES (?, ?)",
            (tn, ln),
        )
        updates = {k: v for k, v in tender.items() if k not in _PRESERVED}
        if updates:
            set_clause = ", ".join(f"{k}=?" for k in updates)
            conn.execute(
                f"UPDATE tenders SET {set_clause}, last_updated_date=? "
                "WHERE tender_number=? AND line_number=?",
                [*updates.values(), today, tn, ln],
            )
        conn.commit()
    finally:
        conn.close()


def sweep_closed_tenders() -> int:
    """Mark tenders whose closing_date is before today as CLOSED. Returns count changed."""
    today = datetime.date.today()
    today_iso = today.isoformat()
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT tender_number, line_number, closing_date FROM tenders "
            "WHERE bid_status != 'CLOSED' AND closing_date IS NOT NULL"
        ).fetchall()

        to_close = []
        for row in rows:
            raw = row["closing_date"]
            try:
                dt = datetime.datetime.strptime(raw[:16], "%d-%m-%Y %H:%M")
                if dt.date() < today:
                    to_close.append((row["tender_number"], row["line_number"]))
            except ValueError:
                pass

        if to_close:
            conn.executemany(
                "UPDATE tenders SET bid_status='CLOSED', last_updated_date=? "
                "WHERE tender_number=? AND line_number=?",
                [(today_iso, tn, ln) for tn, ln in to_close],
            )
            conn.commit()

        return len(to_close)
    finally:
        conn.close()


def get_unscored_tenders() -> list[sqlite3.Row]:
    """Return tenders eligible for Pass 1 scoring."""
    conn = _get_conn()
    try:
        return conn.execute(
            "SELECT * FROM tenders "
            "WHERE pass1_score IS NULL "
            "AND bid_status != 'CLOSED' "
            "AND (run_pass2 IS NULL OR run_pass2 != -1) "
            "ORDER BY closing_date ASC"
        ).fetchall()
    finally:
        conn.close()


def count_rejected_unscored() -> int:
    """Count tenders explicitly blocked from scoring (run_pass2=-1, no Pass 1 score yet)."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM tenders WHERE pass1_score IS NULL AND run_pass2 = -1"
        ).fetchone()
        return row[0]
    finally:
        conn.close()


def update_pass1_score(tn: str, ln: str, fields: dict) -> None:
    """Write Pass 1 scoring columns for one tender."""
    allowed = {
        "pass1_score", "pass1_confidence", "pass1_domain", "pass1_rationale", "pass1_gaps",
        "pass1_recommendation", "pass1_matching_tech",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    conn = _get_conn()
    try:
        set_clause = ", ".join(f"{k}=?" for k in updates)
        conn.execute(
            f"UPDATE tenders SET {set_clause} WHERE tender_number=? AND line_number=?",
            [*updates.values(), tn, ln],
        )
        conn.commit()
    finally:
        conn.close()


def get_unexported_pass1_tender_numbers() -> list[sqlite3.Row]:
    """Return rows with Pass 1 scores not yet written to a delta file."""
    conn = _get_conn()
    try:
        return conn.execute(
            "SELECT * FROM tenders "
            "WHERE pass1_score IS NOT NULL "
            "AND pass1_exported = 0 "
            "AND bid_status != 'CLOSED' "
            "ORDER BY pass1_score DESC, closing_date ASC"
        ).fetchall()
    finally:
        conn.close()


def mark_pass1_exported(tender_list: list[tuple[str, str]]) -> None:
    """Set pass1_exported=1 for the given (tender_number, line_number) pairs."""
    if not tender_list:
        return
    conn = _get_conn()
    try:
        conn.executemany(
            "UPDATE tenders SET pass1_exported=1 WHERE tender_number=? AND line_number=?",
            tender_list,
        )
        conn.commit()
    finally:
        conn.close()


def query_pass2_candidates() -> list[sqlite3.Row]:
    """Return tenders eligible for Pass 2 scoring."""
    conn = _get_conn()
    try:
        return conn.execute(
            "SELECT * FROM tenders "
            "WHERE ("
            "    run_pass2 = 1 "
            "    OR (pass1_score >= ? AND (run_pass2 IS NULL OR run_pass2 = 0))"
            ") "
            "AND pass2_score IS NULL "
            "AND pass2_attempted = 0 "
            "AND bid_status != 'CLOSED' "
            "ORDER BY pass1_score DESC",
            (PASS2_THRESHOLD,),
        ).fetchall()
    finally:
        conn.close()


def set_pass2_attempted(tn: str, ln: str) -> None:
    """Mark pass2_attempted=1 before download begins. Monotone — never resets."""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE tenders SET pass2_attempted=1 WHERE tender_number=? AND line_number=?",
            (tn, ln),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_override(tn: str, ln: str, score: int, reason: str) -> None:
    """Store human override score and reason."""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE tenders SET human_override_score=?, human_override_reason=? "
            "WHERE tender_number=? AND line_number=?",
            (score, reason, tn, ln),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_run_pass2_flag(tn: str, ln: str, value: int) -> None:
    """Set run_pass2 flag (0=auto, 1=force-yes, -1=force-no).
    Never silently downgrades from 1 to 0 — an explicit force-yes cannot be cleared by auto logic.
    """
    if value not in (-1, 0, 1):
        raise ValueError(f"run_pass2 must be -1, 0, or 1; got {value!r}")
    conn = _get_conn()
    try:
        existing = conn.execute(
            "SELECT run_pass2 FROM tenders WHERE tender_number=? AND line_number=?",
            (tn, ln),
        ).fetchone()
        if existing and existing["run_pass2"] == 1 and value == 0:
            return  # auto-reset must not erase an explicit force-yes
        conn.execute(
            "UPDATE tenders SET run_pass2=? WHERE tender_number=? AND line_number=?",
            (value, tn, ln),
        )
        conn.commit()
    finally:
        conn.close()


def log_excel_ingested(filename: str, found: int, applied: int) -> None:
    today = datetime.date.today().isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO excel_log (filename, ingested_date, overrides_found, overrides_applied) "
            "VALUES (?, ?, ?, ?)",
            (filename, today, found, applied),
        )
        conn.commit()
    finally:
        conn.close()


def is_excel_ingested(filename: str) -> bool:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM excel_log WHERE filename=?", (filename,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_few_shot_examples() -> list[sqlite3.Row]:
    """Return the 8 most recent few-shot examples for Pass 1 prompts."""
    conn = _get_conn()
    try:
        return conn.execute(
            "SELECT * FROM few_shot_examples ORDER BY id DESC LIMIT 8"
        ).fetchall()
    finally:
        conn.close()


def add_feedback(
    tn: str, ln: str, original_score: int, corrected_score: int, reason: str
) -> None:
    today = datetime.date.today().isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO feedback "
            "(tender_number, line_number, original_score, corrected_score, reason, created_date) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tn, ln, original_score, corrected_score, reason, today),
        )
        conn.commit()
    finally:
        conn.close()


def add_few_shot_example(title: str, score: int, reason: str) -> None:
    today = datetime.date.today().isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO few_shot_examples (tender_title, correct_score, reason, created_date) "
            "VALUES (?, ?, ?, ?)",
            (title, score, reason, today),
        )
        conn.commit()
    finally:
        conn.close()

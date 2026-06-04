"""
All SQLite operations for the GEM bid database.
Connection is opened/closed per function call for simplicity and safety.
"""

import sqlite3
import datetime
from config import DB_PATH

_STALE_CONSECUTIVE_THRESHOLD = 5   # Stop pagination after N consecutive stale bids


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all 5 tables if they do not exist. Called once at startup."""
    _migrate()
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS bids (
                bid_number              TEXT PRIMARY KEY,
                internal_id             TEXT,
                ministry                TEXT,
                organization            TEXT,
                department              TEXT,
                items                   TEXT,
                quantity                INTEGER,
                start_date              TEXT,
                end_date                TEXT,
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
                emd_amount              TEXT,
                human_override_score    INTEGER,
                human_override_reason   TEXT,
                run_pass2               INTEGER DEFAULT 0,
                exclusion_matched       TEXT,
                pass2_attempted         INTEGER DEFAULT 0,
                bid_status              TEXT DEFAULT 'NEW',
                previous_end_date       TEXT,
                extension_count         INTEGER DEFAULT 0,
                first_seen_date         TEXT,
                last_seen_at            TEXT,
                last_updated_date       TEXT,
                pass1_exported          INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                bid_number          TEXT REFERENCES bids(bid_number),
                original_score      INTEGER,
                corrected_score     INTEGER,
                reason              TEXT,
                promoted_to_rule    INTEGER DEFAULT 0,
                created_date        TEXT
            );

            CREATE TABLE IF NOT EXISTS exclusion_rules (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern         TEXT UNIQUE,
                reason          TEXT,
                source          TEXT,
                created_date    TEXT
            );

            CREATE TABLE IF NOT EXISTS few_shot_examples (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                bid_title       TEXT,
                correct_score   INTEGER,
                reason          TEXT,
                created_date    TEXT
            );

            CREATE TABLE IF NOT EXISTS excel_log (
                filename            TEXT PRIMARY KEY,
                ingested_date       TEXT,
                overrides_found     INTEGER,
                overrides_applied   INTEGER
            );
        """)


def _migrate():
    """Add columns introduced after initial schema creation. Safe to run repeatedly."""
    migrations = [
        "ALTER TABLE bids ADD COLUMN pass2_attempted  INTEGER DEFAULT 0",
        "ALTER TABLE bids ADD COLUMN bid_status       TEXT DEFAULT 'NEW'",
        "ALTER TABLE bids ADD COLUMN previous_end_date TEXT",
        "ALTER TABLE bids ADD COLUMN extension_count  INTEGER DEFAULT 0",
        "ALTER TABLE bids ADD COLUMN last_seen_at     TEXT",
        "ALTER TABLE bids ADD COLUMN emd_amount       TEXT",
        "ALTER TABLE bids ADD COLUMN pass1_exported   INTEGER DEFAULT 0",
    ]
    with _get_conn() as conn:
        for sql in migrations:
            try:
                conn.execute(sql)
            except Exception:
                pass  # Column already exists


def _is_rejected(run_pass2, human_override_score) -> bool:
    """True if a bid should be skipped by all automated processing."""
    if run_pass2 == -1:
        return True
    if human_override_score is not None and human_override_score <= 0:
        return True
    return False


def upsert_raw_bid(bid: dict) -> dict:
    """
    Store raw fetch fields. Handles bid_status transitions and extension detection.
    - New bid  → bid_status = NEW
    - Re-fetch, end_date changed, not rejected → bid_status = EXTENDED, extension_count++
    - Re-fetch, end_date unchanged, not CLOSED → bid_status = ACTIVE
    - Re-fetch, end_date unchanged, CLOSED     → stays CLOSED
    Updates last_seen_at on every successful observation.
    Returns {"is_new": bool, "is_extended": bool}.
    """
    now   = datetime.datetime.now(datetime.UTC).isoformat()
    today = datetime.date.today().isoformat()

    with _get_conn() as conn:
        cur = conn.execute(
            "SELECT end_date, bid_status, extension_count, "
            "run_pass2, human_override_score "
            "FROM bids WHERE bid_number = ?",
            (bid["bid_number"],)
        )
        existing = cur.fetchone()

        if not existing:
            conn.execute("""
                INSERT INTO bids (
                    bid_number, internal_id, ministry, organization, department,
                    items, quantity, start_date, end_date,
                    run_pass2, bid_status, extension_count,
                    first_seen_date, last_seen_at, last_updated_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'NEW', 0, ?, ?, ?)
            """, (
                bid["bid_number"], bid.get("internal_id"), bid.get("ministry"),
                bid.get("organization"), bid.get("department"), bid.get("items"),
                bid.get("quantity"), bid.get("start_date"), bid.get("end_date"),
                today, now, today
            ))
            return {"is_new": True, "is_extended": False}

        stored_end   = existing["end_date"]
        incoming_end = bid.get("end_date")
        rejected     = _is_rejected(existing["run_pass2"], existing["human_override_score"])

        is_extended      = False
        new_status       = existing["bid_status"]
        new_ext_count    = existing["extension_count"] or 0
        previous_end     = None

        if incoming_end and stored_end and incoming_end != stored_end and not rejected:
            is_extended   = True
            new_status    = "EXTENDED"
            new_ext_count += 1
            previous_end  = stored_end
        elif existing["bid_status"] == "CLOSED":
            new_status = "CLOSED"   # Don't reopen on re-fetch with unchanged end_date
        else:
            new_status = "ACTIVE"

        if previous_end is not None:
            conn.execute("""
                UPDATE bids SET
                    internal_id=?, ministry=?, organization=?, department=?,
                    items=?, quantity=?, start_date=?, end_date=?,
                    bid_status=?, extension_count=?, previous_end_date=?,
                    last_seen_at=?, last_updated_date=?,
                    pass1_exported=0
                WHERE bid_number=?
            """, (
                bid.get("internal_id"), bid.get("ministry"), bid.get("organization"),
                bid.get("department"), bid.get("items"), bid.get("quantity"),
                bid.get("start_date"), bid.get("end_date"),
                new_status, new_ext_count, previous_end,
                now, today, bid["bid_number"]
            ))
        else:
            conn.execute("""
                UPDATE bids SET
                    internal_id=?, ministry=?, organization=?, department=?,
                    items=?, quantity=?, start_date=?, end_date=?,
                    bid_status=?, extension_count=?,
                    last_seen_at=?, last_updated_date=?
                WHERE bid_number=?
            """, (
                bid.get("internal_id"), bid.get("ministry"), bid.get("organization"),
                bid.get("department"), bid.get("items"), bid.get("quantity"),
                bid.get("start_date"), bid.get("end_date"),
                new_status, new_ext_count,
                now, today, bid["bid_number"]
            ))

        return {"is_new": False, "is_extended": is_extended}


def upsert_bid(bid: dict):
    """
    INSERT OR REPLACE a bid after scoring. Preserves all human-owned and
    system-lifecycle fields from the existing row.
    pass2_attempted is monotone — once 1, never reverts to 0.
    """
    today = datetime.date.today().isoformat()

    with _get_conn() as conn:
        cur = conn.execute(
            "SELECT human_override_score, human_override_reason, run_pass2, "
            "first_seen_date, pass2_attempted, "
            "bid_status, extension_count, previous_end_date, last_seen_at, emd_amount, "
            "pass1_exported "
            "FROM bids WHERE bid_number = ?",
            (bid["bid_number"],)
        )
        existing = cur.fetchone()

        if existing:
            human_override_score  = existing["human_override_score"]
            human_override_reason = existing["human_override_reason"]
            run_pass2             = existing["run_pass2"]
            first_seen_date       = existing["first_seen_date"]
            pass2_attempted       = max(existing["pass2_attempted"] or 0,
                                        bid.get("pass2_attempted") or 0)
            bid_status            = existing["bid_status"]
            extension_count       = existing["extension_count"] or 0
            previous_end_date     = existing["previous_end_date"]
            last_seen_at          = existing["last_seen_at"]
            emd_amount            = bid.get("emd_amount") or existing["emd_amount"]
            pass1_exported        = existing["pass1_exported"] or 0
        else:
            human_override_score  = None
            human_override_reason = None
            run_pass2             = 0
            first_seen_date       = today
            pass2_attempted       = bid.get("pass2_attempted") or 0
            bid_status            = "NEW"
            extension_count       = 0
            previous_end_date     = None
            last_seen_at          = None
            emd_amount            = bid.get("emd_amount")
            pass1_exported        = 0

        conn.execute("""
            INSERT OR REPLACE INTO bids (
                bid_number, internal_id, ministry, organization, department,
                items, quantity, start_date, end_date,
                pass1_score, pass1_confidence, pass1_domain, pass1_rationale, pass1_gaps,
                pass2_score, pass2_confidence, pass2_domain, pass2_rationale, pass2_gaps,
                pass2_recommendation, emd_amount,
                human_override_score, human_override_reason, run_pass2,
                exclusion_matched, pass2_attempted,
                bid_status, extension_count, previous_end_date,
                first_seen_date, last_seen_at, last_updated_date,
                pass1_exported
            ) VALUES (
                :bid_number, :internal_id, :ministry, :organization, :department,
                :items, :quantity, :start_date, :end_date,
                :pass1_score, :pass1_confidence, :pass1_domain, :pass1_rationale, :pass1_gaps,
                :pass2_score, :pass2_confidence, :pass2_domain, :pass2_rationale, :pass2_gaps,
                :pass2_recommendation, :emd_amount,
                :human_override_score, :human_override_reason, :run_pass2,
                :exclusion_matched, :pass2_attempted,
                :bid_status, :extension_count, :previous_end_date,
                :first_seen_date, :last_seen_at, :last_updated_date,
                :pass1_exported
            )
        """, {
            **bid,
            "human_override_score":  human_override_score,
            "human_override_reason": human_override_reason,
            "run_pass2":             run_pass2,
            "pass2_attempted":       pass2_attempted,
            "bid_status":            bid_status,
            "extension_count":       extension_count,
            "previous_end_date":     previous_end_date,
            "first_seen_date":       first_seen_date,
            "last_seen_at":          last_seen_at,
            "last_updated_date":     today,
            "emd_amount":            emd_amount,
            "pass1_exported":        pass1_exported,
            "pass2_score":           bid.get("pass2_score"),
            "pass2_confidence":      bid.get("pass2_confidence"),
            "pass2_domain":          bid.get("pass2_domain"),
            "pass2_rationale":       bid.get("pass2_rationale"),
            "pass2_gaps":            bid.get("pass2_gaps"),
            "pass2_recommendation":  bid.get("pass2_recommendation"),
        })


def sweep_closed_bids() -> int:
    """
    Lightweight CLOSED-state sweep. Transitions any bid with end_date < TODAY
    to CLOSED regardless of whether it was recently fetched.
    Returns count of newly closed bids.
    """
    today = datetime.date.today().isoformat()
    with _get_conn() as conn:
        cur = conn.execute(
            "UPDATE bids SET bid_status = 'CLOSED' "
            "WHERE end_date < ? AND bid_status != 'CLOSED'",
            (today,)
        )
        return cur.rowcount


def get_unscored_bids() -> list[dict]:
    """
    Return bids eligible for Pass 1 scoring:
    - Not yet scored (pass1_score IS NULL)
    - Not CLOSED
    - Not rejected (run_pass2 != -1)
    - Not manually declined (human_override_score > 0 or not set)
    """
    with _get_conn() as conn:
        cur = conn.execute(
            """
            SELECT * FROM bids
            WHERE pass1_score IS NULL
              AND bid_status != 'CLOSED'
              AND (run_pass2 IS NULL OR run_pass2 != -1)
              AND (human_override_score IS NULL OR human_override_score > 0)
            """
        )
        return [dict(row) for row in cur.fetchall()]


def get_unexported_pass1_bid_numbers() -> list[str]:
    """Return bid_numbers that are Pass-1-scored but not yet exported to a delta file."""
    with _get_conn() as conn:
        cur = conn.execute(
            """
            SELECT bid_number FROM bids
            WHERE pass1_score IS NOT NULL
              AND pass1_exported = 0
              AND bid_status != 'CLOSED'
            """
        )
        return [row[0] for row in cur.fetchall()]


def mark_pass1_exported(bid_numbers: list[str]):
    """Mark bids as exported to the pass1 delta file."""
    if not bid_numbers:
        return
    placeholders = ",".join("?" * len(bid_numbers))
    with _get_conn() as conn:
        conn.execute(
            f"UPDATE bids SET pass1_exported = 1 WHERE bid_number IN ({placeholders})",
            bid_numbers
        )


def count_rejected_unscored() -> int:
    """Count unscored bids skipped due to rejection, decline, or CLOSED status."""
    with _get_conn() as conn:
        cur = conn.execute(
            """
            SELECT COUNT(*) FROM bids
            WHERE pass1_score IS NULL
              AND (
                  bid_status = 'CLOSED'
                  OR run_pass2 = -1
                  OR (human_override_score IS NOT NULL AND human_override_score <= 0)
              )
            """
        )
        return cur.fetchone()[0]


def upsert_override(bid_number: str, score: int, reason: str):
    """Update only the human_override_* columns for an existing bid."""
    with _get_conn() as conn:
        conn.execute(
            "UPDATE bids SET human_override_score = ?, human_override_reason = ?, "
            "last_updated_date = ? WHERE bid_number = ?",
            (score, reason, datetime.date.today().isoformat(), bid_number)
        )


def upsert_run_pass2_flag(bid_number: str, value: int):
    """
    Set run_pass2 flag. Values: 1 = Y (include), -1 = N (exclude), 0 = default.
    Once set to 1 (Y), never downgrades — human YES is permanent until changed back to Y.
    Upgrade from -1 → 1 is allowed (human changes mind from N to Y).
    """
    with _get_conn() as conn:
        cur = conn.execute(
            "SELECT run_pass2 FROM bids WHERE bid_number = ?", (bid_number,)
        )
        row = cur.fetchone()
        if row is None:
            return
        if row["run_pass2"] == 1 and value != 1:
            return  # Never downgrade from Y
        conn.execute(
            "UPDATE bids SET run_pass2 = ?, last_updated_date = ? WHERE bid_number = ?",
            (value, datetime.date.today().isoformat(), bid_number)
        )


def set_pass2_attempted(bid_number: str):
    """Mark a bid as having had a Pass 2 attempt, preventing future retries on failure."""
    with _get_conn() as conn:
        conn.execute(
            "UPDATE bids SET pass2_attempted = 1, last_updated_date = ? WHERE bid_number = ?",
            (datetime.date.today().isoformat(), bid_number)
        )


def query_pass2_candidates() -> list[dict]:
    """
    Return bids eligible for Pass 2 scoring, not yet scored or attempted.

    Inclusion rules:
      - run_pass2 = 1  (human explicitly marked Y) — always include, score irrelevant
      - pass1_score >= PASS2_THRESHOLD AND run_pass2 != -1  (auto-threshold, not excluded)

    Exclusion rules:
      - run_pass2 = -1  (human explicitly marked N) — always exclude
      - pass2_score IS NOT NULL  — already scored
      - pass2_attempted = 1  — previously attempted and failed (no endless retries)
      - bid_status = CLOSED  — deadline has passed
    """
    from config import PASS2_THRESHOLD
    with _get_conn() as conn:
        cur = conn.execute(
            """
            SELECT * FROM bids
            WHERE pass2_score IS NULL
              AND (pass2_attempted IS NULL OR pass2_attempted = 0)
              AND bid_status != 'CLOSED'
              AND (
                  run_pass2 = 1
                  OR (pass1_score >= ? AND (run_pass2 IS NULL OR run_pass2 != -1))
              )
            """,
            (PASS2_THRESHOLD,)
        )
        return [dict(row) for row in cur.fetchall()]


def get_exclusion_rules() -> list[dict]:
    """Return all exclusion rules as list of dicts with pattern, reason, source."""
    with _get_conn() as conn:
        cur = conn.execute("SELECT pattern, reason, source FROM exclusion_rules")
        return [dict(row) for row in cur.fetchall()]


def get_few_shot_examples() -> list[dict]:
    """Return most recent 8 few-shot examples."""
    with _get_conn() as conn:
        cur = conn.execute(
            "SELECT bid_title, correct_score, reason FROM few_shot_examples "
            "ORDER BY id DESC LIMIT 8"
        )
        return [dict(row) for row in cur.fetchall()]


def add_feedback(bid_number: str, corrected_score: int, reason: str):
    """Insert a feedback record, auto-reading original pass1_score from bids table."""
    today = datetime.date.today().isoformat()
    with _get_conn() as conn:
        cur = conn.execute(
            "SELECT pass1_score FROM bids WHERE bid_number = ?", (bid_number,)
        )
        row = cur.fetchone()
        original_score = row["pass1_score"] if row else None
        conn.execute(
            "INSERT INTO feedback (bid_number, original_score, corrected_score, reason, created_date) "
            "VALUES (?, ?, ?, ?, ?)",
            (bid_number, original_score, corrected_score, reason, today)
        )


def add_few_shot_example(bid_title: str, correct_score: int, reason: str):
    """Insert a new few-shot example."""
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO few_shot_examples (bid_title, correct_score, reason, created_date) "
            "VALUES (?, ?, ?, ?)",
            (bid_title, correct_score, reason, datetime.date.today().isoformat())
        )


def add_exclusion_rule(pattern: str, reason: str, source: str):
    """INSERT OR IGNORE — silently skips if pattern already exists."""
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO exclusion_rules (pattern, reason, source, created_date) "
            "VALUES (?, ?, ?, ?)",
            (pattern, reason, source, datetime.date.today().isoformat())
        )


def log_excel_ingested(filename: str, overrides_found: int, overrides_applied: int):
    """Record that an Excel file has been ingested."""
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO excel_log "
            "(filename, ingested_date, overrides_found, overrides_applied) "
            "VALUES (?, ?, ?, ?)",
            (filename, datetime.date.today().isoformat(), overrides_found, overrides_applied)
        )


def is_excel_ingested(filename: str) -> bool:
    """Return True if this filename already appears in excel_log."""
    with _get_conn() as conn:
        cur = conn.execute(
            "SELECT 1 FROM excel_log WHERE filename = ?", (filename,)
        )
        return cur.fetchone() is not None


def update_pass1_score(bid_number: str, score_fields: dict):
    """Update only Pass 1 score fields for an existing bid."""
    with _get_conn() as conn:
        conn.execute("""
            UPDATE bids SET pass1_score=?, pass1_confidence=?, pass1_domain=?,
            pass1_rationale=?, pass1_gaps=?, exclusion_matched=?, last_updated_date=?
            WHERE bid_number=?
        """, (score_fields.get("pass1_score"), score_fields.get("pass1_confidence"),
              score_fields.get("pass1_domain"), score_fields.get("pass1_rationale"),
              score_fields.get("pass1_gaps"), score_fields.get("exclusion_matched"),
              datetime.date.today().isoformat(), bid_number))


def get_orgs_with_bids() -> set[str]:
    """Return the set of organization names that already have bids in the DB."""
    with _get_conn() as conn:
        cur = conn.execute("SELECT DISTINCT organization FROM bids")
        return {row["organization"] for row in cur.fetchall()}


def get_all_excel_logs() -> list[dict]:
    """Return all excel_log records ordered by most recent first."""
    with _get_conn() as conn:
        cur = conn.execute("SELECT * FROM excel_log ORDER BY ingested_date DESC")
        return [dict(row) for row in cur.fetchall()]

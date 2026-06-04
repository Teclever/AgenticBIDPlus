import sqlite3

from config import DB_PATH
from modules.db import add_feedback, add_few_shot_example


def _get_pass1_score(tn: str, ln: str) -> int | None:
    """Return the current pass1_score for a tender, or None if not found."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT pass1_score FROM tenders WHERE tender_number=? AND line_number=?",
            (tn, ln),
        ).fetchone()
        return int(row["pass1_score"]) if row and row["pass1_score"] is not None else None
    finally:
        conn.close()


def process_feedback(
    tn: str,
    ln: str,
    original_title: str,
    corrected_score: int,
    reason: str,
) -> None:
    """Record an analyst override and add a calibration example for Pass 1.

    Writes to the feedback table (original vs corrected score) and to
    few_shot_examples (tender title + corrected score + reason).
    HAL has no exclusion_rules table — pattern promotion is not applicable.
    """
    original_score = _get_pass1_score(tn, ln) or 0
    add_feedback(tn, ln, original_score, corrected_score, reason)
    if original_title:
        add_few_shot_example(original_title, corrected_score, reason)

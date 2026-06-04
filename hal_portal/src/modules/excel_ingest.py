import glob
import os

import pandas as pd

from config import EXPORTS_DIR
from modules.db import (
    is_excel_ingested,
    log_excel_ingested,
    upsert_override,
    upsert_run_pass2_flag,
)
from modules.feedback import process_feedback


def _to_str(val) -> str:
    """Normalise a cell value to a clean string.

    Handles NaN, numeric floats written as '1.0', and trailing whitespace.
    """
    s = str(val).strip()
    if s in ("nan", "None", ""):
        return ""
    # Excel sometimes writes integer line numbers as '1.0' — strip the .0
    if s.endswith(".0") and s[:-2].lstrip("-").isdigit():
        return s[:-2]
    return s


def ingest_excel(filepath: str, force: bool = False) -> dict:
    """Read a pass1 (or bids) Excel file and sync human-editable columns to DB.

    Reads three columns written by the analyst:
      - Run Pass 2          → upsert_run_pass2_flag  (Y → 1, N → -1, blank → skip)
      - Human Override Score → upsert_override + process_feedback
      - Human Override Reason → stored alongside the override score

    Returns a summary dict. Skips the file if already ingested unless force=True.
    The composite primary key is (Tender Number, Line Number).
    """
    filename = os.path.basename(filepath)

    if not force and is_excel_ingested(filename):
        print(f"  [skip] {filename} already ingested.")
        return {"skipped": True}

    try:
        df = pd.read_excel(filepath, dtype=str)
    except Exception as e:
        print(f"  [error] Could not read {filename}: {e}")
        return {"error": str(e)}

    df = df.fillna("")

    overrides_found   = 0
    overrides_applied = 0

    for _, row in df.iterrows():
        tn = _to_str(row.get("Tender Number", ""))
        ln = _to_str(row.get("Line Number",   ""))

        if not tn or not ln:
            continue

        run_pass2       = _to_str(row.get("Run Pass 2",            "")).upper()
        override_score  = _to_str(row.get("Human Override Score",  ""))
        override_reason = _to_str(row.get("Human Override Reason", ""))
        description     = _to_str(row.get("Tender Description",    ""))

        # Sync Run Pass 2 flag: Y → 1, N → -1, blank → no change
        if run_pass2 == "Y":
            upsert_run_pass2_flag(tn, ln, 1)
        elif run_pass2 == "N":
            upsert_run_pass2_flag(tn, ln, -1)

        if not override_score:
            continue

        overrides_found += 1
        try:
            score = int(float(override_score))
            if not (0 <= score <= 5):
                raise ValueError(f"score {score} out of range 0–5")
            upsert_override(tn, ln, score, override_reason)
            process_feedback(
                tn, ln,
                original_title=description,
                corrected_score=score,
                reason=override_reason,
            )
            overrides_applied += 1
        except Exception as e:
            print(f"  [warn] Override for ({tn}, {ln}) skipped: {e}")

    log_excel_ingested(filename, overrides_found, overrides_applied)
    print(
        f"  [ingest] {filename}: "
        f"{overrides_applied}/{overrides_found} overrides applied."
    )
    return {
        "skipped":           False,
        "overrides_found":   overrides_found,
        "overrides_applied": overrides_applied,
    }


def ingest_all_pending() -> None:
    """Ingest any pass1_*.xlsx files in EXPORTS_DIR that have not yet been processed.

    Called at the start of every `run` command to pick up analyst edits from
    previous days before the new scrape begins.
    """
    pattern = os.path.join(str(EXPORTS_DIR), "pass1_*.xlsx")
    all_files = sorted(glob.glob(pattern))

    if not all_files:
        return

    for fp in all_files:
        filename = os.path.basename(fp)
        if not is_excel_ingested(filename):
            print(f"  [ingest] Processing {filename} …")
            ingest_excel(fp)

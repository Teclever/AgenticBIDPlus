"""Excel ingest — read reviewer decisions from a workbook back into the DB.

Maps the `Run Pass 2` column (Y -> 1, N -> -1, blank -> unchanged) and the
optional override score/reason into `bids`. Accepts both the formatted header
(`Tender ID`) and the raw column (`tender_id`). The `excel_log` table makes
ingest idempotent unless `force=True` is passed. The daily `run` never calls
this automatically — ingest is always an explicit action (DB stays master).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import EXPORTS_DIR
from modules.db import already_ingested, log_ingest, update_human_inputs
from modules.logutil import log_info, log_step, log_warn


def ingest_excel(path: str, force: bool = False) -> tuple[int, int]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    if not force and already_ingested(p.name):
        log_step(f"skip {p.name} (already ingested)")
        return (0, 0)

    log_info(f"Reading {p.name}…")
    df = pd.read_excel(p)
    log_step(f"{len(df)} row(s) in spreadsheet")
    overrides_found = 0
    overrides_applied = 0
    for _, row in df.iterrows():
        tender_id = str(row.get("Tender ID", "") or row.get("tender_id", "")).strip()
        if not tender_id or tender_id.lower() == "nan":
            continue
        run_val = _parse_run_pass2(row.get("Run Pass 2"))
        override_score = _parse_score(row.get("Human Override Score"))
        override_reason = _clean_str(row.get("Human Override Reason"))
        if run_val is not None or override_score is not None or override_reason is not None:
            overrides_found += 1
        update_human_inputs(tender_id, run_val, override_score, override_reason)
        if run_val is not None or override_score is not None or override_reason is not None:
            overrides_applied += 1

    log_ingest(p.name, overrides_found, overrides_applied)
    log_info(f"Ingest done: {p.name} — overrides found={overrides_found}, applied={overrides_applied}")
    return overrides_found, overrides_applied


def ingest_all_pending() -> None:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(EXPORTS_DIR.glob("bids_*.xlsx"))
    if not files:
        log_info("No bids_*.xlsx files in exports/ to ingest.")
        return
    log_info(f"Checking {len(files)} bids_*.xlsx file(s) for pending ingest…")
    ingested = 0
    for xlsx in files:
        before = already_ingested(xlsx.name)
        found, applied = ingest_excel(str(xlsx), force=False)
        if not before and (found or applied):
            ingested += 1
    log_info(f"Pending ingest finished ({ingested} file(s) updated this run).")


def _parse_run_pass2(value) -> int | None:
    s = _clean_str(value)
    if s is None:
        return None
    s = s.upper()
    if s == "Y":
        return 1
    if s == "N":
        return -1
    return None


def _parse_score(value) -> int | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        score = int(value)
    except Exception:
        return None
    if 0 <= score <= 5:
        return score
    return None


def _clean_str(value) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    s = str(value).strip()
    return s or None

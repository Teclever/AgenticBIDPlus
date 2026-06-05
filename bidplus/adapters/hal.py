"""HAL portal adapter (S1).

Wraps the existing, tested HAL tool by shelling out to its CLI — never importing
the HAL ``config`` / ``modules`` packages (they use absolute imports that collide
in ``sys.modules`` with the other tools). The subprocess runs with cwd = the HAL
``src`` dir and an env carrying ``BIDPLUS_RUNTIME_DIR`` + ``ANTHROPIC_API_KEY`` so
HAL's own ``config.py`` resolves its writable state under
``$BIDPLUS_RUNTIME_DIR/hal/``.

Run counts are derived by diffing the HAL ``bids.db`` (opened read-only) before
and after the subprocess — the adapter does not parse stdout for counts.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import bidplus.config as config
from bidplus.adapters.base import FetchedDoc, RunResult

# Repo root: bidplus/adapters/hal.py -> parents[2] == BidAnalysisPortal/
_REPO_ROOT = Path(__file__).resolve().parents[2]
_HAL_SRC = _REPO_ROOT / "hal_portal" / "src"


class HALAdapter:
    """``PortalAdapter`` implementation for the HAL portal."""

    portal: str = "hal"

    def __init__(self) -> None:
        # Captured stdout+stderr of the last subprocess run, for the launcher's log.
        self.last_output: str = ""

    # ── paths / env ──────────────────────────────────────────────────────────

    def tool_db_path(self) -> str:
        """HAL's own bids.db under $BIDPLUS_RUNTIME_DIR/hal/ (never in the source tree)."""
        return str(config.portal_dir("hal") / "bids.db")

    # normalized scoring record (Decision #9-A): tool row -> common shape. The shared
    # scorer (S5) is portal-agnostic; this field map is the only per-portal scoring code.
    _SCORING = {
        "table": "tenders",
        "pk": ("tender_number", "line_number"),
        "text": "tender_description",  # same column the miner used — gram set must match
        "fields": {"buyer": "buyer", "value": "estimated_cost",
                   "closing_date": "closing_date", "description": "qualification_criteria"},
    }

    def scoring_records(self, where: str = "1=1"):
        """Tool rows as portal-agnostic NormalizedRecords (the S5 scorer's input)."""
        from bidplus.scoring import read_records
        return read_records(self.portal, self.tool_db_path(), self._SCORING, where)

    def _subprocess_env(self) -> dict[str, str]:
        env = {**os.environ}
        env["BIDPLUS_RUNTIME_DIR"] = str(config.RUNTIME_DIR)
        if config.ANTHROPIC_API_KEY:
            env["ANTHROPIC_API_KEY"] = config.ANTHROPIC_API_KEY
        return env

    # ── DB snapshot (read-only) ──────────────────────────────────────────────

    def _snapshot(self) -> tuple[set[tuple[str, str]], int, int]:
        """Return (key set, scored count, CLOSED count) from the HAL DB.

        Opens the sqlite file read-only. Missing file or missing table -> empty.
        """
        db_path = self.tool_db_path()
        if not os.path.exists(db_path):
            return set(), 0, 0
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
        except sqlite3.OperationalError:
            return set(), 0, 0
        try:
            rows = conn.execute(
                "SELECT tender_number, line_number, pass1_score, bid_status FROM tenders"
            ).fetchall()
        except sqlite3.OperationalError:
            return set(), 0, 0
        finally:
            conn.close()

        keys: set[tuple[str, str]] = set()
        scored = 0
        closed = 0
        for r in rows:
            keys.add((str(r["tender_number"]), str(r["line_number"])))
            if r["pass1_score"] is not None:
                scored += 1
            if r["bid_status"] == "CLOSED":
                closed += 1
        return keys, scored, closed

    # ── pipeline ─────────────────────────────────────────────────────────────

    def run_pipeline(self) -> RunResult:
        before_keys, before_scored, before_closed = self._snapshot()

        start = time.monotonic()
        proc = subprocess.run(
            [sys.executable, "hal_tool.py", "scrape-score"],
            cwd=str(_HAL_SRC),
            env=self._subprocess_env(),
            capture_output=True,
            text=True,
        )
        elapsed = time.monotonic() - start

        self.last_output = (
            f"$ {sys.executable} hal_tool.py scrape-score\n"
            f"[cwd] {_HAL_SRC}\n"
            f"[returncode] {proc.returncode}\n\n"
            f"--- stdout ---\n{proc.stdout}\n"
            f"--- stderr ---\n{proc.stderr}\n"
        )

        after_keys, after_scored, after_closed = self._snapshot()

        status = "success" if proc.returncode == 0 else "failed"
        error_summary = None
        if status == "failed":
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-20:]
            error_summary = "\n".join(tail) if tail else f"exit code {proc.returncode}"

        return RunResult(
            portal=self.portal,
            status=status,
            new_count=len(after_keys - before_keys),
            updated_count=0,
            closed_count=max(0, after_closed - before_closed),
            scored_count=max(0, after_scored - before_scored),
            error_summary=error_summary,
            stage_timings={"run_pipeline": elapsed},
        )

    # ── dry-run view ─────────────────────────────────────────────────────────

    def explain(self, source_pk: str) -> dict:
        tn, _, ln = source_pk.partition("|")
        proc = subprocess.run(
            [sys.executable, "hal_tool.py", "explain", tn, ln],
            cwd=str(_HAL_SRC),
            env=self._subprocess_env(),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"hal_tool.py explain failed (exit {proc.returncode}): "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"explain did not return valid JSON: {e}\n--- stdout ---\n{proc.stdout}"
            ) from e

    # ── documents (built at S5) ──────────────────────────────────────────────

    def fetch_documents(self, source_pk: str) -> list[FetchedDoc]:
        raise NotImplementedError("HAL document fetch is built at S5")

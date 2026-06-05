"""ISRO portal adapter (S2).

Wraps the existing, tested ISRO tool by shelling out to its CLI — never importing
the ISRO ``config`` / ``modules`` packages (they use absolute imports that collide
in ``sys.modules`` with the other tools). The subprocess runs with cwd = the ISRO
tool dir and an env carrying ``BIDPLUS_RUNTIME_DIR`` + ``ANTHROPIC_API_KEY`` so
ISRO's own ``config.py`` resolves its writable state under
``$BIDPLUS_RUNTIME_DIR/isro/``.

Run counts are derived by diffing the ISRO ``bids.db`` (opened read-only) before
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

# Repo root: bidplus/adapters/isro.py -> parents[2] == BidAnalysisPortal/
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ISRO_DIR = _REPO_ROOT / "isro_portal"


class ISROAdapter:
    """``PortalAdapter`` implementation for the ISRO portal."""

    portal: str = "isro"

    def __init__(self) -> None:
        # Captured stdout+stderr of the last subprocess run, for the launcher's log.
        self.last_output: str = ""

    # ── paths / env ──────────────────────────────────────────────────────────

    def tool_db_path(self) -> str:
        """ISRO's own bids.db under $BIDPLUS_RUNTIME_DIR/isro/ (never in the source tree)."""
        return str(config.portal_dir("isro") / "bids.db")

    def _subprocess_env(self) -> dict[str, str]:
        env = {**os.environ}
        env["BIDPLUS_RUNTIME_DIR"] = str(config.RUNTIME_DIR)
        if config.ANTHROPIC_API_KEY:
            env["ANTHROPIC_API_KEY"] = config.ANTHROPIC_API_KEY
        return env

    # ── DB snapshot (read-only) ──────────────────────────────────────────────

    def _snapshot(self) -> tuple[set[str], int, int]:
        """Return (key set, scored count, CLOSED count) from the ISRO DB.

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
                "SELECT tender_id, pass1_score, bid_status FROM bids"
            ).fetchall()
        except sqlite3.OperationalError:
            return set(), 0, 0
        finally:
            conn.close()

        keys: set[str] = set()
        scored = 0
        closed = 0
        for r in rows:
            keys.add(str(r["tender_id"]))
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
            [sys.executable, "isro_tool.py", "scrape-score"],
            cwd=str(_ISRO_DIR),
            env=self._subprocess_env(),
            capture_output=True,
            text=True,
        )
        elapsed = time.monotonic() - start

        self.last_output = (
            f"$ {sys.executable} isro_tool.py scrape-score\n"
            f"[cwd] {_ISRO_DIR}\n"
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
        proc = subprocess.run(
            [sys.executable, "isro_tool.py", "explain", source_pk],
            cwd=str(_ISRO_DIR),
            env=self._subprocess_env(),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"isro_tool.py explain failed (exit {proc.returncode}): "
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
        raise NotImplementedError("ISRO document fetch is built at S5")

"""S7 — lifecycle + retention sweep + overnight-budget check.

Three terminal, idempotent housekeeping passes the nightly cycle runs after Pass 2, plus a
budget report:

1. ``closed_sweep`` — mark every bid whose closing date has PASSED as ``bid_status='CLOSED'`` in
   the parent table (CLOSED is terminal), then delete that bid's residual staged files. The
   parent ROW and its overlay (``summary_json`` / ``local_extract_json`` / flags) are RETAINED —
   only the on-disk documents go. ``bid_status``/the closing-date column are mirrored (tool-owned),
   so a later merge may briefly re-open a past-closing bid; the sweep runs LAST each cycle and
   re-closes it, so the parent settles CLOSED for the day (self-healing).
2. ``retention_sweep`` — the strict N-day (``config.RETENTION_DAYS``) file-retention rule: delete
   any staged file older than the window, keep newer ones (a bid clicked within the window keeps
   its files), and remove dirs that empty out. This — NOT per-bid immediate deletion — is the
   deletion mechanism. The DB is the durable artifact.
3. ``reap_orphans`` — crash-safety: remove ``bids/<pk>/`` dirs that match no parent row (a fetch
   that died before its row landed, or stale leftovers). Conservative: a dir is an orphan only if
   no parent row maps to it.
4. ``budget_report`` — from the latest overall ``scrape_runs`` row, report whether the cycle
   finished before ``config.OVERNIGHT_DEADLINE`` (the ~9am gate), with per-stage timings.

Per-portal closing-date column + PK come from each adapter's ``_SCORING`` spec (HAL
``closing_date`` / ISRO ``bid_closing_date`` / GeM ``end_date``) — no hardcoded duplication.
"""

from __future__ import annotations

import datetime
import json
import shutil
import sqlite3

import bidplus.config as config
from bidplus import runs as _runs
from bidplus.adapters.gem import GeMAdapter
from bidplus.adapters.hal import HALAdapter
from bidplus.adapters.halc import HALCAdapter
from bidplus.adapters.isro import ISROAdapter

_ADAPTERS = {"hal": HALAdapter, "halc": HALCAdapter, "isro": ISROAdapter, "gem": GeMAdapter}

# Closing-date string formats seen across portals (parse_closing also handles ISO-8601 first):
#   HAL  '22-06-2026 17:00'        (%d-%m-%Y %H:%M)
#   ISRO '02-July-2026 15:10'      (%d-%B-%Y %H:%M)
#   GeM  '2026-06-15T11:00:00Z'    (ISO-8601, handled separately)
_DATE_FORMATS = (
    "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y",
    "%d-%B-%Y %H:%M:%S", "%d-%B-%Y %H:%M", "%d-%B-%Y",
    "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y",
)


def _portal_spec(portal: str) -> tuple[tuple[str, ...], str]:
    """(pk columns, closing-date column) for a portal, read from its adapter spec."""
    s = _ADAPTERS[portal]._SCORING
    return tuple(s["pk"]), s["fields"]["closing_date"]


def parse_closing(value) -> datetime.datetime | None:
    """Parse a portal closing-date string to a naive local datetime, or None if unparseable.

    ISO-8601 (GeM, incl. trailing 'Z') is tried first; then the day-first numeric/month-name
    formats HAL/ISRO use. tz is dropped — comparisons are coarse (has the deadline passed)."""
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    try:  # GeM ISO-8601, e.g. 2026-06-15T11:00:00Z
        dt = datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(v, fmt)
        except ValueError:
            continue
    return None


def _pk_where(pk: tuple[str, ...]) -> str:
    return " AND ".join(f"{c}=?" for c in pk)


def _source_pk(row: sqlite3.Row, pk: tuple[str, ...]) -> str:
    """The '|'-joined source PK (the form bid_staging_dir expects)."""
    return "|".join(str(row[c]) for c in pk)


# ── (1) CLOSED sweep ─────────────────────────────────────────────────────────────────

def _remove_closed_files(parent: sqlite3.Connection, portal: str,
                         pk: tuple[str, ...], table: str) -> int:
    """Delete the staging dir of every CLOSED bid (idempotent — already-gone dirs skip)."""
    removed = 0
    for r in parent.execute(f"SELECT {', '.join(pk)} FROM {table} WHERE bid_status='CLOSED'"):
        d = config.bid_staging_dir(portal, _source_pk(r, pk))
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    return removed


def closed_sweep(parent: sqlite3.Connection,
                 now: datetime.datetime | None = None) -> dict:
    """Mark past-closing bids CLOSED (retain row + overlay) and delete CLOSED bids' files."""
    now = now or datetime.datetime.now()
    out: dict = {}
    for portal in config.PORTALS:
        pk, date_col = _portal_spec(portal)
        table = f"{portal}_bids"
        try:
            rows = parent.execute(
                f"SELECT {', '.join(pk)}, {date_col} AS cdate, bid_status FROM {table}"
            ).fetchall()
        except sqlite3.OperationalError:  # table not created yet (no merge has run)
            out[portal] = {"newly_closed": 0, "files_removed": 0, "unparsed_dates": 0}
            continue
        newly = 0
        unparsed = 0
        where = _pk_where(pk)
        for r in rows:
            if (r["bid_status"] or "") == "CLOSED":
                continue
            dt = parse_closing(r["cdate"])
            if dt is None:
                if r["cdate"]:
                    unparsed += 1
                continue
            if dt < now:
                parent.execute(f"UPDATE {table} SET bid_status='CLOSED' WHERE {where}",
                               tuple(r[c] for c in pk))
                newly += 1
        parent.commit()
        removed = _remove_closed_files(parent, portal, pk, table)
        out[portal] = {"newly_closed": newly, "files_removed": removed, "unparsed_dates": unparsed}
    return out


# ── (2) retention sweep ──────────────────────────────────────────────────────────────

def retention_sweep(now: datetime.datetime | None = None,
                    days: int | None = None) -> dict:
    """Delete staged files older than ``days`` (default ``config.RETENTION_DAYS``); keep newer;
    remove dirs that empty out. Filesystem-only — never touches the DB."""
    days = config.RETENTION_DAYS if days is None else days
    cutoff = (now or datetime.datetime.now()).timestamp() - days * 86400
    out: dict = {}
    for portal in config.PORTALS:
        bids_root = config.portal_dir(portal) / "bids"
        files_deleted = empty_removed = 0
        if bids_root.is_dir():
            for biddir in list(bids_root.iterdir()):
                if not biddir.is_dir():
                    continue
                for f in list(biddir.rglob("*")):
                    if f.is_file():
                        try:
                            if f.stat().st_mtime < cutoff:
                                f.unlink()
                                files_deleted += 1
                        except OSError:
                            pass
                if not any(biddir.iterdir()):
                    try:
                        biddir.rmdir()
                        empty_removed += 1
                    except OSError:
                        pass
        out[portal] = {"files_deleted": files_deleted, "empty_dirs_removed": empty_removed}
    return out


# ── (3) orphan reaping ───────────────────────────────────────────────────────────────

def reap_orphans(parent: sqlite3.Connection) -> dict:
    """Remove ``bids/<pk>/`` dirs that map to NO parent row (crash leftovers). A dir is kept iff
    some parent row's sanitised PK equals its name — so a fetch in flight (its row already merged)
    is never reaped, and a genuine orphan always is."""
    out: dict = {}
    for portal in config.PORTALS:
        pk, _ = _portal_spec(portal)
        table = f"{portal}_bids"
        try:
            rows = parent.execute(f"SELECT {', '.join(pk)} FROM {table}").fetchall()
        except sqlite3.OperationalError:
            out[portal] = {"orphan_dirs_removed": 0}
            continue
        valid = {config.bid_staging_dir(portal, _source_pk(r, pk)).name for r in rows}
        bids_root = config.portal_dir(portal) / "bids"
        removed = 0
        if bids_root.is_dir():
            for d in list(bids_root.iterdir()):
                if d.is_dir() and d.name not in valid:
                    shutil.rmtree(d, ignore_errors=True)
                    removed += 1
        out[portal] = {"orphan_dirs_removed": removed}
    return out


# ── (4) overnight budget check ───────────────────────────────────────────────────────

def _deadline_after(start: datetime.datetime, hhmm: str) -> datetime.datetime:
    """The first wall-clock ``hhmm`` at or after ``start`` (same day if still ahead, else next)."""
    h, m = (int(x) for x in hhmm.split(":"))
    cand = start.replace(hour=h, minute=m, second=0, microsecond=0)
    if cand < start:
        cand += datetime.timedelta(days=1)
    return cand


def budget_report(parent: sqlite3.Connection,
                  deadline: str | None = None,
                  now: datetime.datetime | None = None) -> dict:
    """From the latest overall (``tool IS NULL``) scrape_runs row, report whether the cycle
    finished before the configured deadline, with duration + per-stage timings."""
    row = parent.execute(
        "SELECT id, started_at, finished_at, stage_timings_json FROM scrape_runs "
        "WHERE tool IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return {"status": "no_runs"}
    started = datetime.datetime.fromisoformat(row["started_at"])
    finished = (datetime.datetime.fromisoformat(row["finished_at"])
                if row["finished_at"] else (now or datetime.datetime.now()))
    deadline_dt = _deadline_after(started, deadline or config.OVERNIGHT_DEADLINE)
    return {
        "run_id": row["id"],
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "in_progress": row["finished_at"] is None,
        "deadline": deadline_dt.isoformat(timespec="seconds"),
        "within_budget": finished <= deadline_dt,
        "duration_seconds": round((finished - started).total_seconds(), 1),
        "stage_timings": json.loads(row["stage_timings_json"] or "{}"),
    }


def run_sweep(parent: sqlite3.Connection, now: datetime.datetime | None = None) -> dict:
    """The full nightly housekeeping pass (CLOSED → retention → orphans → alert purge). Idempotent."""
    purged = _runs.purge_old_cleared(parent, days=10)
    return {
        "closed": closed_sweep(parent, now=now),
        "retention": retention_sweep(now=now),
        "orphans": reap_orphans(parent),
        "alerts_purged": purged,
    }

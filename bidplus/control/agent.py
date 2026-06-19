"""The control-plane agent — a single-worker poll loop.

Each tick (every ``POLL_SECS``) the agent, using only outbound calls:
  1. finishes/monitors an in-flight commanded run (non-blocking subprocess);
  2. detects a freshly-finished AUTONOMOUS cycle (the 01:00 nightly) and publishes it;
  3. claims the first pending row in the Commands tab and launches it;
  4. rewrites the Status tab (heartbeat + per-portal snapshot + alerts);
  5. prunes old dated bid-list tabs.

Restart-safety: a command is marked ``running`` in the Sheet BEFORE its subprocess starts
and recorded in a local state file. On startup any of our rows still ``running`` are marked
``interrupted`` (systemd's default KillMode killed the child on restart) — never re-run, so
no double execution. Status reporting covers autonomous runs too, not just commanded ones.

This layer TRIGGERS and REPORTS only — it never makes bid recommendations.
"""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
import time
import traceback

from bidplus.control import commands, report, settings
from bidplus.control.sheets import Book

BID_HEADER = ["Portal", "Bid ID", "Title", "Organization", "Pass-1 Score", "Summary"]
RUNS_HEADER = ["Finished", "Cycle ID", "Trigger", "Status", "Duration(s)", "Portals",
               "New", "Scored", "Keyword-Elim", "Model-Scored", "Summarized",
               "Summary-Failed", "Closed", "Errors"]


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _dur(started: str | None, finished: str | None) -> str:
    try:
        a = datetime.datetime.fromisoformat(started)
        b = datetime.datetime.fromisoformat(finished)
        return str(int((b - a).total_seconds()))
    except Exception:
        return ""


class Agent:
    def __init__(self) -> None:
        self.book = Book()
        self.start_mono = time.monotonic()
        self.proc: subprocess.Popen | None = None
        self.state = self._load_state()

    # ── local state (idempotency / recovery) ──────────────────────────────────
    def _load_state(self) -> dict:
        try:
            return json.loads(settings.STATE_FILE.read_text())
        except Exception:
            return {"last_published_run_id": None, "inflight": None}

    def _save_state(self) -> None:
        settings.STATE_DIR.mkdir(parents=True, exist_ok=True)
        settings.STATE_FILE.write_text(json.dumps(self.state, indent=2))

    # ── startup recovery ───────────────────────────────────────────────────────
    def recover(self) -> None:
        """Mark any of our rows left mid-flight as 'interrupted' (no re-run)."""
        self.state["inflight"] = None
        self._save_state()
        grid = self.book.grid(settings.TAB_COMMANDS)
        for idx, values in enumerate(grid[1:], start=2):  # skip header; 1-based row
            d = commands.parse_row(values)
            if d["status"].lower() in ("running", "claimed") and d["worker"] == settings.WORKER:
                d.update(status="interrupted", finished_at=_now(),
                         result="agent restarted mid-command; not re-run")
                self._write_command(idx, d)

    # ── the loop ───────────────────────────────────────────────────────────────
    def run_forever(self) -> None:
        self.book.refresh()
        self._ensure_tabs()
        self.recover()
        print(f"[control] agent up (worker={settings.WORKER} poll={settings.POLL_SECS}s)", flush=True)
        while True:
            try:
                self.tick()
            except Exception:
                print("[control] tick error:\n" + traceback.format_exc(), flush=True)
            time.sleep(settings.POLL_SECS)

    def tick(self) -> None:
        self.book.refresh()  # one worksheet-list read per tick; all lookups below are cache hits
        conn = report.connect()
        try:
            activity = "idle"
            # 1. in-flight command: still running, or just finished?
            if self.state.get("inflight"):
                if self.proc is not None and self.proc.poll() is None:
                    inf = self.state["inflight"]
                    activity = f"running {inf['kind']} {inf['portal']}".rstrip()
                else:
                    self._finish_command(conn)  # clears inflight
            # 2. worker free -> publish any autonomous cycle, then claim a command.
            if not self.state.get("inflight"):
                self._publish_autonomous(conn)
                if self._claim_and_launch(conn):
                    inf = self.state["inflight"]
                    activity = f"running {inf['kind']} {inf['portal']}".rstrip()
                elif report.running_cycle(conn) is not None:
                    activity = "nightly cycle in progress"
            # 3. heartbeat + status
            self._publish_status(conn, activity)
        finally:
            conn.close()
        # 4. prune dated tabs (cheap, outside the DB scope)
        self._prune()

    # ── command lifecycle ───────────────────────────────────────────────────────
    def _claim_and_launch(self, conn) -> bool:
        grid = self.book.grid(settings.TAB_COMMANDS)
        for idx, values in enumerate(grid[1:], start=2):
            d = commands.parse_row(values)
            if not commands.is_pending(d):
                continue
            err = commands.validate(d)
            if err:
                d.update(status="rejected", finished_at=_now(), result=err, worker=settings.WORKER)
                self._write_command(idx, d)
                continue
            # claim — write 'running' to the Sheet BEFORE launching (recovery anchor).
            if not d["command_id"]:
                d["command_id"] = f"{settings.WORKER}-{int(time.time())}"
            if not d["requested_at"]:
                d["requested_at"] = _now()
            d.update(status="running", claimed_at=_now(), started_at=_now(),
                     finished_at="", exit_code="", result="", worker=settings.WORKER)
            self._write_command(idx, d)
            log = settings.CMD_LOG_DIR / f"{d['command_id']}.log"
            self.state["inflight"] = {
                "command_id": d["command_id"], "row": idx, "kind": commands.kind(d),
                "portal": commands.portal_of(d), "launched_at": d["started_at"],
                "log": str(log),
            }
            self._save_state()
            self.proc = commands.launch(d, log)
            print(f"[control] launched {d['command_id']}: {commands.kind(d)} "
                  f"{commands.portal_of(d)}".rstrip(), flush=True)
            return True
        return False

    def _finish_command(self, conn) -> None:
        inf = self.state["inflight"]
        rc = self.proc.poll() if self.proc is not None else None
        ok = rc == 0
        # The launcher finalized its overall scrape_runs row before exiting; find ours.
        cyc = self._our_cycle(conn, inf["launched_at"])
        tab = None
        if cyc is not None:
            trigger = inf["kind"]
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            prefix = settings.PREFIX_RERUN if inf["kind"] == "rerun" else settings.PREFIX_RUN
            tab = (f"{prefix}{inf['portal']} {stamp}" if inf["kind"] == "rerun"
                   else f"{prefix}{stamp}")
            self._publish_cycle(conn, cyc, trigger=trigger, tab=tab)
            self.state["last_published_run_id"] = cyc["id"]
        # write back command result
        grid_row = inf["row"]
        d = commands.parse_row(self.book.grid(settings.TAB_COMMANDS)[grid_row - 1])
        d.update(
            status="done" if ok else "failed",
            finished_at=_now(),
            exit_code="" if rc is None else str(rc),
            result=(f"OK — published to '{tab}'" if (ok and tab)
                    else f"OK (exit {rc})" if ok
                    else f"FAILED (exit {rc}); see {inf['log']}"),
            worker=settings.WORKER,
        )
        self._write_command(grid_row, d)
        print(f"[control] finished {inf['command_id']} rc={rc}", flush=True)
        self.proc = None
        self.state["inflight"] = None
        self._save_state()

    def _our_cycle(self, conn, launched_at: str):
        """The overall scrape_runs cycle our subprocess produced (started at/after launch)."""
        cyc = report.latest_finished_cycle(conn)
        if cyc is None:
            return None
        try:
            if datetime.datetime.fromisoformat(cyc["started_at"]) >= \
               datetime.datetime.fromisoformat(launched_at) - datetime.timedelta(seconds=5):
                return cyc
        except Exception:
            return cyc
        return cyc  # best-effort: latest finished cycle

    # ── autonomous (nightly) publication ────────────────────────────────────────
    def _publish_autonomous(self, conn) -> None:
        cyc = report.latest_finished_cycle(conn)
        if cyc is None:
            return
        if cyc["id"] == self.state.get("last_published_run_id"):
            return
        day = datetime.date.today().isoformat()
        try:
            day = datetime.datetime.fromisoformat(cyc["finished_at"]).date().isoformat()
        except Exception:
            pass
        tab = f"{settings.PREFIX_NIGHTLY}{day}"
        self._publish_cycle(conn, cyc, trigger="nightly", tab=tab)
        self.state["last_published_run_id"] = cyc["id"]
        self._save_state()
        print(f"[control] published autonomous cycle id={cyc['id']} -> '{tab}'", flush=True)

    # ── shared publication: dated bid tab + Runs append ─────────────────────────
    def _publish_cycle(self, conn, cyc, *, trigger: str, tab: str) -> None:
        bids = report.bid_list(conn, settings.PORTALS)
        rows = [[b["portal"], b["bid_id"], b["title"], b["org"], b["score"], b["summary"]]
                for b in bids]
        self.book.overwrite(tab, BID_HEADER, rows)
        portals = report.cycle_portal_rows(conn, cyc["id"])
        self.book.append(settings.TAB_RUNS, RUNS_HEADER, [
            cyc["finished_at"], cyc["id"], trigger, cyc["status"] or "",
            _dur(cyc["started_at"], cyc["finished_at"]),
            ", ".join(p["tool"] for p in portals) or "-",
            cyc["new_count"] or 0, cyc["scored_count"] or 0,
            cyc["keyword_scored_count"] or 0, cyc["model_scored_count"] or 0,
            cyc["summarized_count"] or 0, cyc["summary_failed_count"] or 0,
            cyc["closed_count"] or 0, cyc["error_summary"] or "",
        ])

    # ── Status tab (heartbeat + per-portal snapshot) ────────────────────────────
    def _publish_status(self, conn, activity: str) -> None:
        up = int(time.monotonic() - self.start_mono)
        cyc = report.latest_finished_cycle(conn)
        pmap = {p["tool"]: p for p in report.cycle_portal_rows(conn, cyc["id"])} if cyc else {}
        matrix = [
            ["BidPlus control plane", ""],
            ["Heartbeat", _now()],
            ["Worker", settings.WORKER],
            ["Version", settings.VERSION],
            ["Uptime (s)", up],
            ["Activity", activity],
            ["Last cycle", f"{cyc['started_at']} -> {cyc['finished_at']} ({cyc['status']})"
             if cyc else "(none yet)"],
            [""],
            ["Portal", "Last-cycle status", "New", "Scored", "Keyword-Elim",
             "Model-Scored", "Summarized", "Summary-Failed", "Errors",
             "Total bids", "Score-5 (new)", "Closing ≤10d"],
        ]
        for portal in settings.PORTALS:
            p = pmap.get(portal)
            inv = report.inventory(conn, portal) or {}
            matrix.append([
                portal,
                (p["status"] if p else "—"),
                (p["new_count"] if p else ""),
                (p["scored_count"] if p else ""),
                (p["keyword_scored_count"] if p else ""),
                (p["model_scored_count"] if p else ""),
                (p["summarized_count"] if p else ""),
                (p["summary_failed_count"] if p else ""),
                (p["error_summary"] if p and p["error_summary"] else ""),
                inv.get("total", ""), inv.get("score5_new", ""), inv.get("closing_soon", ""),
            ])
        alerts = report.active_alerts(conn)
        matrix += [[""], [f"Active alerts: {len(alerts)}"]]
        for a in alerts:
            matrix.append([a["alert_type"], a["portal"] or "", a["reason"] or "", a["raised_at"] or ""])
        self.book.put(settings.TAB_STATUS, matrix)

    # ── helpers ─────────────────────────────────────────────────────────────────
    def _write_command(self, row_index: int, d: dict) -> None:
        self.book.write_row(settings.TAB_COMMANDS, row_index, [d[c] for c in commands.COLUMNS])

    def _ensure_tabs(self) -> None:
        self.book.ensure_header(settings.TAB_COMMANDS, commands.COLUMNS)
        self.book.ensure_header(settings.TAB_RUNS, RUNS_HEADER)
        self.book.worksheet(settings.TAB_STATUS, create=True)

    def _prune(self) -> None:
        for prefix in (settings.PREFIX_NIGHTLY, settings.PREFIX_RUN, settings.PREFIX_RERUN):
            try:
                self.book.prune_prefix(prefix, settings.BID_TABS_KEEP)
            except Exception:
                pass


def main() -> int:
    if not settings.SHEET_ID:
        print("[control] BIDPLUS_CONTROL_SHEET_ID is not set — nothing to do.", file=sys.stderr)
        return 2
    Agent().run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

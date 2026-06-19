"""Google Sheets I/O (gspread + service-account auth). Box -> Google only.

Opens the spreadsheet by key (Sheets API; no Drive lookup). The control agent is the
SINGLE writer, so worksheet edits need no cross-process locking. Every public call is one
or two batched API requests, wrapped in a bounded retry for transient 429/5xx so a quota
blip or restart never crashes the loop.
"""

from __future__ import annotations

import random
import time

import gspread
from google.oauth2.service_account import Credentials

from bidplus.control import settings


def _cell(v) -> str:
    """Sheets-safe scalar: None -> '', everything else -> str."""
    return "" if v is None else str(v)


def _retry(fn, *, attempts: int = 5):
    last = None
    for a in range(attempts):
        try:
            return fn()
        except gspread.exceptions.APIError as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (429, 500, 502, 503):  # transient: rate limit / backend
                last = e
                time.sleep(min(2 ** a, 30) + random.uniform(0, 0.5))
                continue
            raise
    raise RuntimeError(f"Sheets API failed after {attempts} attempts: {last!r}")


def open_spreadsheet():
    creds = Credentials.from_service_account_file(settings.SA_KEY, scopes=settings.SCOPES)
    gc = gspread.authorize(creds)
    return _retry(lambda: gc.open_by_key(settings.require_sheet_id()))


class Book:
    """Thin wrapper over one spreadsheet."""

    def __init__(self, spreadsheet=None) -> None:
        self.ss = spreadsheet or open_spreadsheet()

    # ── worksheet access ──────────────────────────────────────────────────────
    def worksheet(self, title, *, create=False, rows=200, cols=26):
        try:
            return self.ss.worksheet(title)
        except gspread.WorksheetNotFound:
            if not create:
                return None
            return _retry(lambda: self.ss.add_worksheet(title=title, rows=rows, cols=cols))

    # ── whole-tab writes ──────────────────────────────────────────────────────
    def put(self, title, matrix) -> None:
        """Replace a tab's contents with ``matrix`` (list of rows). Rows are padded to a
        uniform width and stringified. One clear + one update."""
        rows = [[_cell(v) for v in row] for row in matrix] or [[""]]
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        ws = self.worksheet(title, create=True, rows=max(len(rows) + 10, 50), cols=max(width, 4))
        _retry(lambda: ws.clear())
        _retry(lambda: ws.update(values=rows, range_name="A1", value_input_option="RAW"))

    def overwrite(self, title, header, rows) -> None:
        """Replace a tab with header + data rows."""
        self.put(title, [list(header), *[list(r) for r in rows]])

    # ── append-only ───────────────────────────────────────────────────────────
    def ensure_header(self, title, header):
        ws = self.worksheet(title, create=True, rows=500, cols=max(len(header), 4))
        first = _retry(lambda: ws.row_values(1))
        if first != [_cell(h) for h in header]:
            _retry(lambda: ws.update(values=[[_cell(h) for h in header]],
                                     range_name="A1", value_input_option="RAW"))
        return ws

    def append(self, title, header, row) -> None:
        ws = self.ensure_header(title, header)
        _retry(lambda: ws.append_row([_cell(v) for v in row], value_input_option="RAW"))

    # ── row-level (Commands tab) ──────────────────────────────────────────────
    def grid(self, title) -> list[list[str]]:
        """All values (row 1 = header). [] if the tab is missing."""
        ws = self.worksheet(title)
        if ws is None:
            return []
        return _retry(lambda: ws.get_all_values())

    def write_row(self, title, row_index, values) -> None:
        """Overwrite cells A..N of a 1-based row in one request."""
        ws = self.worksheet(title, create=True)
        _retry(lambda: ws.update(values=[[_cell(v) for v in values]],
                                 range_name=f"A{row_index}", value_input_option="RAW"))

    # ── dated-tab housekeeping ────────────────────────────────────────────────
    def titles(self) -> list[str]:
        return [w.title for w in _retry(lambda: self.ss.worksheets())]

    def prune_prefix(self, prefix, keep) -> list[str]:
        """Delete oldest tabs whose title starts with ``prefix``, keeping the newest ``keep``.
        Titles embed a sortable timestamp, so lexical sort = chronological."""
        matching = sorted(w for w in _retry(lambda: self.ss.worksheets()) if w.title.startswith(prefix))
        drop = matching[:-keep] if keep and len(matching) > keep else []
        for w in drop:
            _retry(lambda w=w: self.ss.del_worksheet(w))
        return [w.title for w in drop]

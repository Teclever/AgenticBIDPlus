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
        self._cache: dict | None = None  # lower(title) -> worksheet

    # ── worksheet access ──────────────────────────────────────────────────────
    def refresh(self) -> None:
        """Re-read the worksheet list (one API call). Call once per tick so all
        lookups within the tick are cache hits (keeps us well under quota)."""
        self._cache = {w.title.strip().lower(): w
                       for w in _retry(lambda: self.ss.worksheets())}

    def worksheet(self, title, *, create=False, rows=200, cols=26):
        """Find a worksheet by title CASE-INSENSITIVELY (Google enforces case-insensitive
        name uniqueness, so a pre-existing 'commands' tab must satisfy a 'Commands' lookup
        and never trigger a duplicate-name create). Creates with the given title on miss."""
        if self._cache is None:
            self.refresh()
        key = title.strip().lower()
        ws = self._cache.get(key)
        if ws is not None:
            return ws
        if not create:
            return None
        ws = _retry(lambda: self.ss.add_worksheet(title=title, rows=rows, cols=cols))
        self._cache[key] = ws
        return ws

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

    # ── bid-list formatting (matches the per-portal Excel export) ─────────────
    # Whole-row fills by Pass-1 score, same hues as excel_export (5 blue / 4 yellow / 3 orange).
    _SCORE_FILLS = {
        "5": {"red": 0.302, "green": 0.651, "blue": 1.0},    # 4DA6FF
        "4": {"red": 1.0, "green": 0.824, "blue": 0.2},      # FFD233
        "3": {"red": 1.0, "green": 0.6, "blue": 0.4},        # FF9966
    }
    # Per-column pixel widths: Portal, Bid ID, Title, Organization, Pass-1 Score, Summary.
    _COL_WIDTHS = [70, 165, 380, 230, 95, 560]

    def format_bid_tab(self, title) -> None:
        """Apply the standard bid-tab look: frozen+bold header, a basic filter (so Title etc.
        are filterable), per-column widths, wrapped multi-line top-aligned cells, and score
        5/4/3 conditional row fills. One batched API call. Best-effort (never breaks publish)."""
        ws = self.worksheet(title)
        if ws is None:
            return
        sid = ws.id
        ncols = len(self._COL_WIDTHS)
        reqs: list = [
            {"updateSheetProperties": {
                "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount"}},
            {"repeatCell": {"range": {"sheetId": sid},
                "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"}},
                "fields": "userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment"}},
            {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold"}},
            {"setBasicFilter": {"filter": {"range": {
                "sheetId": sid, "startRowIndex": 0, "startColumnIndex": 0, "endColumnIndex": ncols}}}},
        ]
        for c, px in enumerate(self._COL_WIDTHS):
            reqs.append({"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c, "endIndex": c + 1},
                "properties": {"pixelSize": px}, "fields": "pixelSize"}})
        # Score column is E (index 4). Values are stored as text, so compare as text.
        for score, color in self._SCORE_FILLS.items():
            reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
                "ranges": [{"sheetId": sid, "startRowIndex": 1,
                            "startColumnIndex": 0, "endColumnIndex": ncols}],
                "booleanRule": {
                    "condition": {"type": "CUSTOM_FORMULA",
                                  "values": [{"userEnteredValue": f'=$E2="{score}"'}]},
                    "format": {"backgroundColor": color}}}}})
        try:
            _retry(lambda: self.ss.batch_update({"requests": reqs}))
        except Exception as e:  # formatting must never break a publish
            print(f"[control] format_bid_tab({title!r}) skipped: {e}", flush=True)

    # ── dated-tab housekeeping ────────────────────────────────────────────────
    def titles(self) -> list[str]:
        if self._cache is None:
            self.refresh()
        return [w.title for w in self._cache.values()]

    def prune_prefix(self, prefix, keep) -> list[str]:
        """Delete oldest tabs whose title starts with ``prefix``, keeping the newest ``keep``.
        Titles embed a sortable timestamp, so lexical sort = chronological."""
        if self._cache is None:
            self.refresh()
        matching = sorted((w for w in self._cache.values() if w.title.startswith(prefix)),
                          key=lambda w: w.title)
        drop = matching[:-keep] if keep and len(matching) > keep else []
        for w in drop:
            _retry(lambda w=w: self.ss.del_worksheet(w))
            self._cache.pop(w.title.strip().lower(), None)
        return [w.title for w in drop]

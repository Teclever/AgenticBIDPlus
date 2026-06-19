"""Control-plane configuration — all via ``BIDPLUS_*`` env vars (no hardcoded secrets/IDs).

Reuses :mod:`bidplus.config` for the runtime root / parent.db / portal list so there is a
single source of truth.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

import bidplus.config as core

# Spreadsheet + auth (the SA key path defaults to the box location; override via env).
SHEET_ID = os.environ.get("BIDPLUS_CONTROL_SHEET_ID", "").strip()
SA_KEY = os.environ.get(
    "BIDPLUS_CONTROL_SA_KEY", "/etc/bidplus/bidplus-control-1b58558711e0.json"
)
# Sheets API only — we open by key (no Drive lookup needed).
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Cadence + retention.
POLL_SECS = int(os.environ.get("BIDPLUS_CONTROL_POLL_SECS", "60"))
BID_TABS_KEEP = int(os.environ.get("BIDPLUS_CONTROL_BID_TABS_KEEP", "14"))

# Identity + local state (idempotency / restart recovery marker).
WORKER = os.environ.get("BIDPLUS_CONTROL_WORKER", socket.gethostname())
STATE_DIR = Path(os.environ.get("BIDPLUS_CONTROL_STATE_DIR", str(core.RUNTIME_DIR / "control")))
STATE_FILE = STATE_DIR / "state.json"
CMD_LOG_DIR = STATE_DIR / "logs"

PORTALS = core.PORTALS
VERSION = "1.0"

# Fixed tab names (the dated bid tabs are created per run/day).
TAB_STATUS = "Status"
TAB_RUNS = "Runs"
TAB_COMMANDS = "Commands"

# Dated-tab prefixes (used for routing + pruning).
PREFIX_NIGHTLY = "Nightly "
PREFIX_RUN = "Run "
PREFIX_RERUN = "Rerun "


def require_sheet_id() -> str:
    if not SHEET_ID:
        raise RuntimeError("BIDPLUS_CONTROL_SHEET_ID is not set.")
    return SHEET_ID

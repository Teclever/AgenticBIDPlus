"""Whitelisted command parsing + execution.

The Commands tab is UNTRUSTED input (Sheet edit access = command authority). Only two
commands exist — ``run`` and ``rerun <portal>`` — each mapped to a FIXED launcher argv
(list form passed straight to ``subprocess``: no shell, no eval, no args interpolated
from the Sheet beyond a portal name validated against the closed PORTALS set).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import bidplus
import bidplus.config as core
from bidplus.control import settings

# Repo root holds the `bidplus` package: bidplus/control/commands.py -> parents[2].
REPO_ROOT = Path(bidplus.__file__).resolve().parents[1]

# Fixed Commands-tab column order. The operator fills command / portal / requested_by;
# the agent owns the rest. Header row (row 1) must match these names.
COLUMNS = [
    "command_id", "command", "portal", "requested_by", "status",
    "requested_at", "claimed_at", "started_at", "finished_at",
    "exit_code", "result", "worker",
]

VALID = {"run", "rerun"}
PENDING = {"", "pending", "queued"}


def parse_row(values: list[str]) -> dict:
    """Map a Commands row (cells aligned to COLUMNS) to a dict; missing cells -> ''."""
    out = {}
    for i, col in enumerate(COLUMNS):
        v = values[i] if i < len(values) and values[i] is not None else ""
        out[col] = v.strip()
    return out


def is_pending(d: dict) -> bool:
    return d["status"].lower() in PENDING


def command_of(d: dict) -> str:
    return d["command"].strip().lower()


def portal_of(d: dict) -> str:
    return d["portal"].strip().lower()


def validate(d: dict) -> str | None:
    """Return an error string if the (pending) row is not an executable command, else None."""
    cmd = command_of(d)
    if cmd not in VALID:
        return f"unknown command {d['command']!r} (allowed: run, rerun)"
    if cmd == "rerun" and portal_of(d) not in settings.PORTALS:
        return (f"rerun requires portal in {{{', '.join(settings.PORTALS)}}}; "
                f"got {d['portal']!r}")
    return None


def argv(d: dict) -> list[str]:
    """The exact, fixed argv for a validated command. No Sheet text reaches the shell."""
    base = [sys.executable, "-m", "bidplus.launcher", "run"]
    if command_of(d) == "rerun":
        base += ["--only", portal_of(d)]
    return base


def kind(d: dict) -> str:
    return command_of(d)  # 'run' | 'rerun'


def launch(d: dict, log_path: Path) -> subprocess.Popen:
    """Start the launcher as a detached-but-tracked child, stdout+stderr -> log_path.

    The child inherits BIDPLUS_RUNTIME_DIR + the parent env (which carries
    ANTHROPIC_API_KEY from the runtime .env loaded by bidplus.config)."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "BIDPLUS_RUNTIME_DIR": str(core.RUNTIME_DIR)}
    logf = open(log_path, "w")
    return subprocess.Popen(
        argv(d), cwd=str(REPO_ROOT), env=env,
        stdout=logf, stderr=subprocess.STDOUT,
    )

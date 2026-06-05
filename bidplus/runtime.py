"""Runtime-path resolution + the iCloud fail-loud guard.

Single source of truth for where writable state lives. Every writable path in the
system (parent.db, per-portal bids.db, document staging, exports, browser profile,
the single .env, the venv) hangs off ``BIDPLUS_RUNTIME_DIR`` resolved here. No
writable path is ever hardcoded inside the iCloud-synced source tree.

The guard is macOS-specific (iCloud syncs ~/Documents and ~/Desktop, which would
corrupt a live SQLite mid-write); it is a no-op on the Ubuntu deploy box.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Same default on both machines: on the Mac it expands to ~/bidplus-runtime; on the
# Ubuntu deploy box (user `congo`) it expands to /home/congo/bidplus-runtime.
DEFAULT_RUNTIME_DIR = "~/bidplus-runtime"

ENV_VAR = "BIDPLUS_RUNTIME_DIR"


def _is_macos() -> bool:
    return sys.platform == "darwin"


def assert_icloud_safe(path: Path) -> None:
    """Refuse a runtime dir that iCloud would sync (macOS only; no-op elsewhere).

    Raises ``RuntimeError`` if ``path`` is under ~/Documents or ~/Desktop, or sits
    inside iCloud's ``Library/Mobile Documents`` backing store.
    """
    if not _is_macos():
        return

    resolved = path.expanduser().resolve()
    home = Path.home().resolve()

    for root in (home / "Documents", home / "Desktop"):
        if resolved == root or root in resolved.parents:
            raise RuntimeError(
                f"{ENV_VAR} ({resolved}) is inside {root}, which iCloud syncs. "
                "A live SQLite synced mid-write WILL corrupt. Choose a path outside "
                "~/Documents and ~/Desktop (e.g. ~/bidplus-runtime)."
            )

    if "Library/Mobile Documents" in str(resolved):
        raise RuntimeError(
            f"{ENV_VAR} ({resolved}) is inside iCloud's Mobile Documents store. "
            "Choose a path outside iCloud (e.g. ~/bidplus-runtime)."
        )


def runtime_root() -> Path:
    """Resolved runtime root (env var or per-OS default), iCloud-guarded."""
    raw = os.environ.get(ENV_VAR, DEFAULT_RUNTIME_DIR)
    root = Path(raw).expanduser().resolve()
    assert_icloud_safe(root)
    return root


def resolve_portal_dir(portal: str) -> Path | None:
    """Per-portal runtime dir when ``BIDPLUS_RUNTIME_DIR`` is set; ``None`` otherwise.

    Tools call this to relocate their writable state under
    ``$BIDPLUS_RUNTIME_DIR/<portal>/``. When the var is unset they fall back to their
    in-tree default, preserving standalone runs.
    """
    if ENV_VAR not in os.environ:
        return None
    return runtime_root() / portal


def capability_reference_path() -> Path:
    """Absolute path to the ONE canonical Pass-1 rubric (decision #8).

    The rubric is read-only reference data committed to git, so it resolves relative
    to the ``bidplus`` package itself — NOT under ``BIDPLUS_RUNTIME_DIR`` (that is for
    writable state only). All three tool configs point here so there is a single
    source of truth and no drift between per-portal copies. Works for both standalone
    tool runs and orchestrated runs because all tools share the one git root.
    """
    return Path(__file__).resolve().parent / "data" / "capability_reference.md"

"""Central configuration: filesystem paths, portal URLs, model names, thresholds.

All other modules import their constants from here so there is a single place to
retune behaviour (batch size, Pass 2 threshold, models, request timeout).
"""

from __future__ import annotations

from pathlib import Path

from bidplus.runtime import capability_reference_path, resolve_portal_dir

BASE_DIR = Path(__file__).resolve().parent
MODULES_DIR = BASE_DIR / "modules"
DATA_DIR = BASE_DIR / "data"

# Writable state relocates under $BIDPLUS_RUNTIME_DIR/isro/ (outside iCloud) when the
# orchestrator sets the env var; falls back to the in-tree default for standalone runs.
_RT = resolve_portal_dir("isro")
if _RT is not None:
    DB_PATH = _RT / "bids.db"
    EXPORTS_DIR = _RT / "exports"
    DOWNLOADS_DIR = _RT / "downloads"
else:
    DB_PATH = DATA_DIR / "bids.db"
    EXPORTS_DIR = BASE_DIR / "exports"
    DOWNLOADS_DIR = BASE_DIR / "downloads"

# One canonical Pass-1 rubric for all three portals (decision #8), in bidplus/data/.
CAPABILITY_REF_PATH = capability_reference_path()

ISRO_BASE_URL = "https://eproc.isro.gov.in"
ISRO_HOME_URL = f"{ISRO_BASE_URL}/home.html"

PASS1_MODEL = "claude-haiku-4-5-20251001"
PASS2_MODEL = "claude-sonnet-4-6"
PASS1_BATCH_SIZE = 20
PASS2_THRESHOLD = 3

REQUEST_TIMEOUT_SECONDS = 60
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def ensure_runtime_dirs() -> None:
    # The dir holding bids.db: the relocated runtime portal dir, or in-tree data/.
    db_parent = _RT if _RT is not None else DATA_DIR
    for path in (db_parent, EXPORTS_DIR, DOWNLOADS_DIR):
        path.mkdir(parents=True, exist_ok=True)

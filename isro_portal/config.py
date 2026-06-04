"""Central configuration: filesystem paths, portal URLs, model names, thresholds.

All other modules import their constants from here so there is a single place to
retune behaviour (batch size, Pass 2 threshold, models, request timeout).
"""

from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MODULES_DIR = BASE_DIR / "modules"
DATA_DIR = BASE_DIR / "data"
EXPORTS_DIR = BASE_DIR / "exports"
DOWNLOADS_DIR = BASE_DIR / "downloads"

DB_PATH = DATA_DIR / "bids.db"
CAPABILITY_REF_PATH = DATA_DIR / "capability_reference.md"

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
    for path in (DATA_DIR, EXPORTS_DIR, DOWNLOADS_DIR):
        path.mkdir(parents=True, exist_ok=True)

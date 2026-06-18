"""Central configuration: filesystem paths, portal URLs, model names, thresholds.

All other modules import their constants from here so there is a single place to
retune behaviour (batch size, Pass 2 threshold, models, request timeout).

This portal is the HAL corporate tenders site (https://hal-india.co.in/tender),
served by a WordPress REST backend. It is DISTINCT from the HAL e-procurement
portal (eproc.hal-india.co.in) integrated under the ``hal`` key — this one is the
``halc`` portal.

Writable state relocates under $BIDPLUS_RUNTIME_DIR/halc/ (outside iCloud) when the
orchestrator sets the env var; falls back to the in-tree default for standalone runs.
"""

from __future__ import annotations

from pathlib import Path

from bidplus.runtime import capability_reference_path, resolve_portal_dir

BASE_DIR = Path(__file__).resolve().parent
MODULES_DIR = BASE_DIR / "modules"
DATA_DIR = BASE_DIR / "data"

_RT = resolve_portal_dir("halc")
if _RT is not None:
    DB_PATH = _RT / "bids.db"
    EXPORTS_DIR = _RT / "exports"
    DOWNLOADS_DIR = _RT / "downloads"
else:
    DB_PATH = DATA_DIR / "bids.db"
    EXPORTS_DIR = BASE_DIR / "exports"
    DOWNLOADS_DIR = BASE_DIR / "downloads"

# One canonical Pass-1 rubric for all portals (decision #8), in bidplus/data/.
CAPABILITY_REF_PATH = capability_reference_path()

# ── HAL tenders site (WordPress REST backend) ────────────────────────────────
HAL_SITE_URL = "https://hal-india.co.in"
HAL_TENDER_PAGE_URL = f"{HAL_SITE_URL}/tender"            # warms WAF cookies
HAL_API_BASE = f"{HAL_SITE_URL}/backend/wp-json/hal/v1"   # REST namespace
HAL_LIST_ENDPOINT = f"{HAL_API_BASE}/tenders-list"        # POST, empty multipart → {results:[…]}
HAL_DETAIL_ENDPOINT = f"{HAL_API_BASE}/tender_detail"     # POST id=<id> → {results:[{…72 fields…}]}

PASS1_MODEL = "claude-haiku-4-5-20251001"
PASS2_MODEL = "claude-sonnet-4-6"
PASS1_BATCH_SIZE = 20
PASS2_THRESHOLD = 3

# Characters of `detail_text` passed to the Pass 1 prompt per tender.
PASS1_DETAIL_CHARS = 2000

REQUEST_TIMEOUT_SECONDS = 60

# The HAL site sits behind a WAF that blocks bare requests. A browser-like
# User-Agent plus Referer/Origin headers (and cookies warmed from the tender
# page) are required on every call — see modules/fetcher.make_session().
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def ensure_runtime_dirs() -> None:
    db_parent = _RT if _RT is not None else DATA_DIR
    for path in (db_parent, EXPORTS_DIR, DOWNLOADS_DIR):
        path.mkdir(parents=True, exist_ok=True)

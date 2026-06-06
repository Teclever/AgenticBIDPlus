"""Central orchestrator configuration.

Reads ``BIDPLUS_RUNTIME_DIR`` (via :mod:`bidplus.runtime`, which applies the iCloud
guard), resolves all writable paths under it, pins the model IDs, the trigger-only
score gate, the bounded summary-retry cap, and loads the single ANTHROPIC_API_KEY
from the one .env in the runtime dir. No second key source, ever.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from bidplus.runtime import runtime_root

RUNTIME_DIR = runtime_root()
PARENT_DB_PATH = RUNTIME_DIR / "parent.db"
ENV_PATH = RUNTIME_DIR / ".env"

# Single source of secrets: the one .env in the runtime dir. (No per-tool .env files.)
load_dotenv(ENV_PATH)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# --- Model pins (AGENTS.md / plan §5) -------------------------------------------------
PASS1_MODEL = "claude-haiku-4-5-20251001"   # batch Pass-1 scoring
SUMMARY_MODEL = "claude-sonnet-4-6"         # one structured call per bid (vision-capable)
GOVERNANCE_MODEL = "claude-sonnet-4-6"      # periodic eliminator-list AI delta (reasoning-heavy, low volume)

# --- Eliminator governance (ELIMINATOR_DESIGN.md §7–§9) -------------------------------
# A negative term correct on hundreds of junk bids but wrong on one exception is
# insufficient-alone, not bad: at/above HIGH_SUPPORT a false positive marks it
# 'under_review' (fixed by a POSITIVE add), never auto-quarantined.
ELIM_HIGH_SUPPORT = int(os.environ.get("ELIM_HIGH_SUPPORT", "50"))
# The AI delta fires when this many new promotion-reasons accrue OR a week passes.
ELIM_DELTA_PROMOTION_THRESHOLD = int(os.environ.get("ELIM_DELTA_PROMOTION_THRESHOLD", "35"))
ELIM_DELTA_WEEKLY_DAYS = int(os.environ.get("ELIM_DELTA_WEEKLY_DAYS", "7"))

# --- Score gate (TRIGGER ONLY; same summarization module for every score) -------------
# Score 5 is the ONLY automatic Sonnet call (overnight). Score 4 gets a cheap regex
# preview now and the module deferred to a "Fetch more" click. 3/2/1/0 are on demand.
SCORE_AUTO_SUMMARIZE = 5
SCORE_LOCAL_EXTRACT = 4

# --- Summarization module bounds (plan §8b) -------------------------------------------
SUMMARY_MAX_ATTEMPTS = int(os.environ.get("SUMMARY_MAX_ATTEMPTS", "3"))  # initial + retries
SUMMARY_TOKEN_BUDGET = int(os.environ.get("SUMMARY_TOKEN_BUDGET", "150000"))

# --- File retention + overnight budget (S7 nightly sweep) -----------------------------
RETENTION_DAYS = int(os.environ.get("BIDPLUS_RETENTION_DAYS", "7"))
# The cycle starts ~3am and must finish by ~9am (plan "Overnight budget"). The S7 budget
# check compares the cycle's finished_at against this wall-clock deadline (local time).
OVERNIGHT_DEADLINE = os.environ.get("BIDPLUS_OVERNIGHT_DEADLINE", "09:00")

# --- Our identity (single-vendor / single-tender favourability, S6 Channel 2) ---------
# A single-vendor tender restricted to US is a pursue; restricted to anyone else is dead.
# Detected LOCALLY (no Sonnet). Comma-separated aliases, matched case-insensitively.
OUR_VENDOR_ALIASES = [a.strip().lower() for a in
                      os.environ.get("OUR_VENDOR_ALIASES", "teclever").split(",") if a.strip()]

# Strict sequential scrape order (HAL -> ISRO -> GeM). One heavy op at a time.
PORTALS = ("hal", "isro", "gem")


def portal_dir(portal: str) -> Path:
    """Runtime dir for a portal: $BIDPLUS_RUNTIME_DIR/<portal>/."""
    return RUNTIME_DIR / portal


def bid_staging_dir(portal: str, source_pk: str) -> Path:
    """Per-bid document staging dir. Source PKs with '/' (HAL tender numbers) are
    sanitised to '_' for the path."""
    safe = str(source_pk).replace("/", "_")
    return portal_dir(portal) / "bids" / safe


def require_api_key() -> str:
    """Return the API key or fail loud (used by code paths that actually call Sonnet)."""
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Put it in the single "
            f"{ENV_PATH} (or the environment)."
        )
    return ANTHROPIC_API_KEY

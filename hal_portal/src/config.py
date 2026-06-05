import os
import socket
import urllib.parse
from pathlib import Path
from dotenv import load_dotenv

from bidplus.runtime import capability_reference_path, resolve_portal_dir, runtime_root

BASE_DIR = Path(__file__).parent

# Writable state relocates under $BIDPLUS_RUNTIME_DIR/hal/ (outside iCloud) when the
# orchestrator sets the env var; falls back to the in-tree default for standalone runs.
_RT = resolve_portal_dir("hal")

# Single .env: load the one in the runtime dir when relocated, else the in-tree default.
if _RT is not None:
    load_dotenv(runtime_root() / ".env")
    DB_PATH             = _RT / "bids.db"
    EXPORTS_DIR         = _RT / "exports"
    DOWNLOADS_DIR       = _RT / "downloads"
    BROWSER_PROFILE_DIR = _RT / ".browser_profile"
else:
    load_dotenv()
    DB_PATH             = BASE_DIR / "data" / "bids.db"
    EXPORTS_DIR         = BASE_DIR / "exports"
    DOWNLOADS_DIR       = BASE_DIR / "downloads"
    BROWSER_PROFILE_DIR = BASE_DIR / ".browser_profile"

# One canonical Pass-1 rubric for all three portals (decision #8), in bidplus/data/.
CAPABILITY_REF_PATH = capability_reference_path()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

PASS1_MODEL     = "claude-haiku-4-5-20251001"
PASS2_MODEL     = "claude-sonnet-4-6"
PASS2_THRESHOLD = 3

# Entry point for the Aurelia SPA (HAL portal home)
HAL_BASE_URL = "https://eproc.hal-india.co.in/HAL/"

# Persistent Playwright browser profile — reused across runs so the portal
# session survives between scrape and pass-2 without re-authenticating.
# (BROWSER_PROFILE_DIR is resolved above — runtime dir when relocated, else in-tree.)

SCRAPE_DELAY_SECONDS = 0.7   # polite delay between portal requests
PASS1_BATCH_SIZE     = 25
PASS2_LOW_TEXT_CHARS = 500   # threshold for base64 PDF fallback

# PDF folder names keyed by recommendation (upper-cased)
REC_TO_FOLDER = {
    "PURSUE":               "Pursue",
    "PURSUE WITH RAMP-UP":  "Pursue_with_Ramp_Up",
    "ASSESS FURTHER":       "Assess_Further",
    "DECLINE":              "Decline",
}


# ── Browser launch ───────────────────────────────────────────────────────────
# The HAL portal host publishes multiple A-records and occasionally leaves one
# unreachable. Headless Chromium (unlike curl) does not fail over quickly and
# will hang the full navigation timeout on a dead IP. We probe the resolved
# addresses at launch time and pin Chromium to the first reachable one via
# --host-resolver-rules so navigation always targets a live server.

def _first_reachable_ip(host: str, port: int = 443, timeout: float = 4.0) -> str | None:
    """Return the first A-record IP for `host` that accepts a TCP connection."""
    try:
        infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror:
        return None
    seen: set[str] = set()
    for *_, sockaddr in infos:
        ip = sockaddr[0]
        if ip in seen:
            continue
        seen.add(ip)
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return ip
        except OSError:
            continue
    return None


def chromium_launch_args() -> list[str]:
    """Chromium args shared by every launch_persistent_context call.

    Includes a --host-resolver-rules mapping pinning the portal host to a
    reachable IP when one of its A-records is down. Computed fresh per launch
    so it adapts to whichever address is live at the time.
    """
    args = ["--disable-blink-features=AutomationControlled"]
    host = urllib.parse.urlparse(HAL_BASE_URL).hostname
    if host:
        ip = _first_reachable_ip(host)
        if ip:
            args.append(f"--host-resolver-rules=MAP {host} {ip}")
            print(f"  [net] Pinned {host} -> {ip} (reachable A-record)", flush=True)
        else:
            print(f"  [net] WARNING: no reachable IP for {host}; using system DNS.", flush=True)
    return args

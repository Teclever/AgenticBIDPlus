import json, os
from pathlib import Path

from bidplus.runtime import capability_reference_path, resolve_portal_dir

BASE_DIR = Path(__file__).parent
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

with open(BASE_DIR / "data" / "organizations.json") as f:
    TARGET_ORGS = {k: v for k, v in json.load(f).items() if not k.startswith("_")}

# Writable state relocates under $BIDPLUS_RUNTIME_DIR/gem/ (outside iCloud) when the
# orchestrator sets the env var; falls back to the in-tree default for standalone runs.
_RT = resolve_portal_dir("gem")
if _RT is not None:
    _RT.mkdir(parents=True, exist_ok=True)
    DB_PATH       = str(_RT / "bids.db")
    STATE_PATH    = str(_RT / "state.json")
    EXPORTS_DIR   = str(_RT / "exports")
    DOWNLOADS_DIR = str(_RT / "downloads")
else:
    DB_PATH       = str(BASE_DIR / "data" / "bids.db")
    STATE_PATH    = str(BASE_DIR / "data" / "state.json")
    EXPORTS_DIR   = str(BASE_DIR / "exports")
    DOWNLOADS_DIR = str(BASE_DIR / "downloads")

# One canonical Pass-1 rubric for all three portals (decision #8), in bidplus/data/.
CAPABILITY_REF_PATH   = str(capability_reference_path())

PASS2_THRESHOLD        = 3
EXCLUSION_AUTO_PROMOTE = 0

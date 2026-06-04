import json, os
from pathlib import Path

BASE_DIR = Path(__file__).parent
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

with open(BASE_DIR / "data" / "organizations.json") as f:
    TARGET_ORGS = {k: v for k, v in json.load(f).items() if not k.startswith("_")}

DB_PATH               = str(BASE_DIR / "data" / "bids.db")
STATE_PATH            = str(BASE_DIR / "data" / "state.json")
EXPORTS_DIR           = str(BASE_DIR / "exports")
DOWNLOADS_DIR         = str(BASE_DIR / "downloads")
CAPABILITY_REF_PATH   = str(BASE_DIR / "data" / "capability_reference.md")

PASS2_THRESHOLD        = 3
EXCLUSION_AUTO_PROMOTE = 0

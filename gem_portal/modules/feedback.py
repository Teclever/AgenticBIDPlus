"""
When a bid is overridden to score 0 with a reason, this module:
1. Saves it as a few-shot example (for moderate correction cases)
2. Optionally promotes a clear keyword pattern to exclusion_rules
"""

from modules.db import add_feedback, add_few_shot_example, add_exclusion_rule
from config import EXCLUSION_AUTO_PROMOTE

# Known high-confidence exclusion patterns (seeded at init)
SEED_EXCLUSION_PATTERNS = [
    ("Customized AMC/CMC for Pre-owned Products",
     "Procurement of AMC/license for third-party software — not an engineering engagement"),
    # NOTE: Generic "AMC of" and "CAMC of" are intentionally NOT excluded —
    # AMC/CAMC contracts for ATEs and Test Rigs are in scope.
    # NOTE: "Procurement of" is intentionally NOT excluded —
    # work packages for SW development, IV&V, and testing are in scope.
    ("Rate Contract for",
     "Rate contract procurement — commodity supply, not engineering services"),
    # NOTE: "Hiring of" is intentionally NOT excluded —
    # manpower bids for SW development, IV&V, and testing are in scope.
    ("Supply of",
     "Supply of goods — check further but likely not engineering"),
    ("Printing of",
     "Printing/stationery procurement"),
    ("Housekeeping",
     "Facility management — out of scope"),
]


def seed_exclusion_rules():
    """Called once at DB init to pre-populate known patterns."""
    for pattern, reason in SEED_EXCLUSION_PATTERNS:
        add_exclusion_rule(pattern, reason, source="seed")


def process_feedback(bid_number: str, original_title: str,
                     corrected_score: int, reason: str):
    """
    Called after each override is written. Decides whether to:
    - Add a few-shot example (all corrections)
    - Promote to exclusion rule (score <= EXCLUSION_AUTO_PROMOTE)
    """
    add_feedback(bid_number, corrected_score, reason)
    add_few_shot_example(original_title, corrected_score, reason)

    if corrected_score <= EXCLUSION_AUTO_PROMOTE and reason:
        # Extract a potential pattern: first 40 chars of title (heuristic)
        # Human can review exclusion_rules.json and clean up
        candidate_pattern = original_title[:40].strip()
        add_exclusion_rule(candidate_pattern, reason, source="feedback")
        print(f"  [feedback] Promoted pattern to exclusion_rules: '{candidate_pattern}'")

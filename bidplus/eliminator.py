"""Pre-Pass-1 two-pass eliminator gate + governance schema/seed (S5).

`eliminate = neg_hit AND NOT pos_hit`. The negative match is byte-for-byte faithful to
``bidplus/scripts/mine_eliminators.py`` (``grams`` + ``_eliminates``); the positive list
is a high-precision veto that rescues a tripped bid to Haiku.

The live lists are **DB rows** in ``eliminator_terms`` (parent.db), read fresh each run.
The mined JSON artifacts seed that table once at first deploy; thereafter governance owns
it (ledger + AI delta + Excel review — see ``ELIMINATOR_DESIGN.md``). This module covers
the schema, the idempotent seed, the gate, and shadow analysis. The Haiku scoring engine
and the AI-delta governance loop are separate (scoring chunk 2 / governance chunk 3).
"""

from __future__ import annotations

import datetime
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

_DATA = Path(__file__).resolve().parent / "data"
_NEG_SEED = _DATA / "eliminator_keywords.json"
_POS_SEED = _DATA / "inscope_signals.json"

# Negative tokeniser — MUST match the miner exactly. Positive tokeniser per the seed
# (_meta.matching): tokens are word-boundary [a-z0-9-]{2,}; phrases are substring.
_TOK = re.compile(r"[a-z]{3,}")
_POS_TOK_RE = re.compile(r"[a-z0-9\-]{2,}")

# Ordinary English the capability doc happens to contain — these guarded candidates are
# DROPPED at seed (the miner's `excluded_generic_unigrams`): they neither fire directly
# nor count toward the two-signal rule. The remaining guarded candidates become the active
# two-signal guards. MUST match mine_eliminators.GUARDED_NOISE.
_GUARDED_NOISE = set("not use general field section cross medium auto hard customized".split())


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


# ── schema ───────────────────────────────────────────────────────────────────────

def ensure_schema(parent: sqlite3.Connection) -> None:
    """Create the three governance tables (idempotent). Live in parent.db."""
    parent.execute(
        "CREATE TABLE IF NOT EXISTS eliminator_terms ("
        " id INTEGER PRIMARY KEY, list_type TEXT NOT NULL, kind TEXT NOT NULL,"
        " term TEXT NOT NULL, is_guarded INTEGER DEFAULT 0, active INTEGER DEFAULT 1,"
        " source TEXT, rationale TEXT, created_at TEXT, UNIQUE(list_type, kind, term))"
    )
    parent.execute(
        "CREATE TABLE IF NOT EXISTS eliminator_keyword_stats ("
        " term TEXT PRIMARY KEY, confirmed_rejections INTEGER DEFAULT 0,"
        " false_positives INTEGER DEFAULT 0, status TEXT DEFAULT 'active')"
    )
    parent.execute(
        "CREATE TABLE IF NOT EXISTS list_change_proposals ("
        " id INTEGER PRIMARY KEY, batch_id TEXT NOT NULL, list_type TEXT NOT NULL,"
        " term TEXT NOT NULL, kind TEXT, change_type TEXT NOT NULL, refine_to TEXT,"
        " risk TEXT, ai_rationale TEXT, source_reasons TEXT,"
        " status TEXT DEFAULT 'proposed', created_at TEXT, decided_at TEXT)"
    )
    parent.commit()


def seed_terms(parent: sqlite3.Connection, force: bool = False) -> dict:
    """Seed ``eliminator_terms`` from the mined JSON. IDEMPOTENT — a no-op if the table
    is already populated (so it never clobbers governance-applied changes), unless
    ``force=True``. The active guarded set is ``guarded_unigrams_two_signal`` ∩ ``words``
    (the noise unigrams were already dropped from ``words`` at mine time)."""
    ensure_schema(parent)
    existing = parent.execute("SELECT COUNT(*) FROM eliminator_terms").fetchone()[0]
    if existing and not force:
        return {"seeded": 0, "existing": existing}
    if force:
        parent.execute("DELETE FROM eliminator_terms")

    neg = json.loads(_NEG_SEED.read_text())
    pos = json.loads(_POS_SEED.read_text())
    meta = neg.get("_meta", {})
    stop = set(meta.get("stopwords", []))
    # The JSON keeps RAW candidates: `words` still includes the noise unigrams and
    # guarded_unigrams_two_signal is the full candidate set. Apply the miner's trim:
    candidates = set(meta.get("guarded_unigrams_two_signal", []))
    guarded = candidates - _GUARDED_NOISE      # active two-signal guards (e.g. 9)
    now = _now()

    def ins(list_type, kind, term, is_guarded=0, active=1) -> None:
        parent.execute(
            "INSERT OR IGNORE INTO eliminator_terms "
            "(list_type, kind, term, is_guarded, active, source, created_at) "
            "VALUES (?,?,?,?,?,'mined',?)",
            (list_type, kind, term, is_guarded, active, now),
        )

    for p in neg["phrases"]:
        ins("neg", "phrase", p)
    for w in neg["words"]:
        # Drop the noise unigrams (recorded active=0 for provenance, never loaded).
        if w in _GUARDED_NOISE:
            ins("neg", "word", w, is_guarded=0, active=0)
        else:
            ins("neg", "word", w, is_guarded=1 if w in guarded else 0)
    for p in pos["phrases"]:
        ins("pos", "phrase", p)
    for tk in pos["tokens"]:
        ins("pos", "token", tk)
    for s in stop:
        ins("stop", "word", s)
    parent.commit()
    return {"seeded": parent.execute("SELECT COUNT(*) FROM eliminator_terms WHERE active=1").fetchone()[0],
            "existing": existing, "guarded": len(guarded)}


# ── live term set (read fresh from the table each run) ─────────────────────────────

@dataclass
class Terms:
    neg_phrases: set = field(default_factory=set)
    neg_words: set = field(default_factory=set)
    guarded: set = field(default_factory=set)
    pos_phrases: list = field(default_factory=list)
    pos_tokens: set = field(default_factory=set)
    stop: set = field(default_factory=set)
    boost_phrases: list = field(default_factory=list)  # auto-promote to score 5


def load_terms(parent: sqlite3.Connection) -> Terms:
    t = Terms()
    for lt, kind, term, g in parent.execute(
        "SELECT list_type, kind, term, is_guarded FROM eliminator_terms WHERE active=1"
    ):
        if lt == "neg" and kind == "phrase":
            t.neg_phrases.add(term)
        elif lt == "neg" and kind == "word":
            t.neg_words.add(term)
            if g:
                t.guarded.add(term)
        elif lt == "pos" and kind == "phrase":
            t.pos_phrases.append(term)
        elif lt == "pos" and kind == "token":
            t.pos_tokens.add(term)
        elif lt == "stop":
            t.stop.add(term)
        elif lt == "boost":
            t.boost_phrases.append(term)
    return t


# Seed terms for the score-5 boost list. INSERT OR IGNORE so reruns and
# governance-added rows are never clobbered; independent of the main seed
# (which no-ops once the table is populated). FULLY-UPPERCASE terms are
# treated as acronyms by boost_match (exact case-sensitive match) — a
# case-insensitive 'ATE'/'AI' would hit the words 'ate'/'ai' and 'AIS'.
_BOOST_SEED = [
    "test rig",
    "ATE",                       # automated test equipment (acronym)
    "automated test equipment",
    "automatic test equipment",
    "AI",                        # artificial intelligence (acronym)
    "artificial intelligence",
    "check out system",          # singular — matcher covers plural + 'checkout'
    "signal conditioner",        # in-scope instrumentation (matcher covers plural)
    "signal conditioning",
]


def ensure_boost_seed(parent: sqlite3.Connection) -> None:
    now = _now()
    for term in _BOOST_SEED:
        parent.execute(
            "INSERT OR IGNORE INTO eliminator_terms "
            "(list_type, kind, term, is_guarded, active, source, created_at) "
            "VALUES ('boost','phrase',?,0,1,'seed',?)",
            (term, now),
        )
    parent.commit()


# ── AMC/CMC org-gated rescue (AMC/CMC handling spec) ───────────────────────────────
# An AMC/CMC maintenance contract normally trips the negative gate. We RESCUE it to Pass-1
# Haiku scoring (instead of auto-eliminating) when:
#   3a  the buyer is a Level-1 organization        -> rescue regardless of item, OR
#   3b  the buyer is any other org AND the item is NOT facilities/IT infrastructure.
# Rescued bids are floored to score 4 unless Haiku independently rates them 5
# (applied in scoring.score_portal). The BOOST list still takes precedence (those bypass
# the gate entirely to score 5). Non-AMC/CMC eliminations are unaffected.

# Portals that are wholly a Level-1 org by definition (the tool itself is the buyer).
LEVEL1_PORTALS = frozenset({"hal", "halc", "isro"})

# Level-1 buyer match (case-insensitive) over the bid's buyer/org text. Acronyms are
# word-boundary anchored; full names are substring. "Office of DG (Aero)" is the DRDO aero
# cluster HQ that procures for ADA/ADE, so it counts as Level-1.
LEVEL1_ORG_RE = re.compile(
    r"hindustan aeronautics|\bHAL\b|"
    r"aeronautical development agenc|\bADA\b|"
    r"aeronautical development establishment|\bADE\b|dg\s*\(?\s*aero\)?|"
    r"indian space research|department of space|\bISRO\b|\bVSSC\b|\bLPSC\b|"
    r"\bSDSC\b|\bSHAR\b|\bIPRC\b|space applications|"
    r"bharat electronics|\bBEL\b|"
    r"combat vehicles|\bCVRDE\b|"
    r"central manufacturing technology|\bCMTI\b|"
    r"indian institute of astrophysics|\bIIAP\b|"
    r"defence research|\bDRDO\b|gas turbine research|\bGTRE\b",
    re.IGNORECASE,
)

# Facilities / IT-infrastructure markers. Used ONLY for non-Level-1 buyers (3b): an AMC/CMC
# bid from a non-Level-1 org that matches any of these stays eliminated. Bare ambiguous
# acronyms (AC, RO) are anchored to their facilities sense to avoid clobbering technical
# bids (e.g. "AC servo drive", an "RO" inside another token).
INFRA_RE = re.compile(
    r"cctv|surveillance|"
    r"fire extinguisher|fire alarm|fire[ -]?fighting|"
    r"air[ -]?condition|chiller|\bHVAC\b|cooling tower|"
    r"\bUPS\b|inverter|battery bank|"
    r"\bDG set\b|diesel generator|"
    r"\bEPABX\b|telephone|intercom|"
    r"biometric|access control|attendance|"
    r"\blift\b|elevator|escalator|"
    r"\bservers?\b|desktop|laptop|printer|photocopier|network switch|\brouter\b|firewall|"
    r"\bstorage\b|it peripheral|\bASRS\b|material handling|"
    r"water cooler|reverse osmosis|\bRO\s+(?:plant|system|unit|water|purif)|"
    r"plumbing|housekeeping|\bcivil\b|building|furniture",
    re.IGNORECASE,
)


# An AMC/CMC maintenance contract, detected from the item text itself (not the matched
# negative terms) so it applies both to gate-tripped bids (rescue) and to bids that survive
# the gate naturally via a positive signal (still floor to 4). 'AMC'/'CMC'/'CAMC' as words
# plus the spelled-out maintenance-contract phrasings.
_AMC_CMC_TEXT_RE = re.compile(
    r"\b(?:c?amc|cmc)\b|annual maintenance|comprehensive maintenance|maintenance contract",
    re.IGNORECASE,
)


def is_amc_cmc_text(text: str | None) -> bool:
    """True if the item text is an AMC/CMC maintenance-contract bid."""
    return bool(_AMC_CMC_TEXT_RE.search(text or ""))


def is_level1(portal: str, buyer: str | None) -> bool:
    """True if the bid's portal is wholly Level-1 or its buyer/org matches a Level-1 org."""
    if portal in LEVEL1_PORTALS:
        return True
    return bool(LEVEL1_ORG_RE.search(buyer or ""))


def is_infrastructure(text: str | None) -> bool:
    """True if the item text is facilities/IT infrastructure (CCTV, chillers, UPS, …)."""
    return bool(INFRA_RE.search(text or ""))


def amc_floor_qualifies(portal: str, buyer: str | None, text: str) -> bool:
    """The single predicate behind both the AMC/CMC gate-rescue and the score-4 floor:
    the bid is an AMC/CMC contract AND (3a) its buyer is Level-1, OR (3b) the item is not
    facilities/IT infrastructure. Used to (1) rescue a gate-tripped AMC/CMC bid to Haiku
    rather than eliminate it, and (2) floor any qualifying AMC/CMC bid that reaches Haiku
    to score 4 unless Haiku rates it 5. Non-AMC/CMC bids return False (unaffected)."""
    if not is_amc_cmc_text(text):
        return False
    return is_level1(portal, buyer) or not is_infrastructure(text)


def boost_match(text: str, boost_phrases: list) -> str | None:
    """First boost phrase matching ``text``, or None.

    Phrases: case-insensitive, whitespace/hyphen tolerant, word-boundary
    anchored, optional plural ('test rig' hits testrig / Test-Rigs).
    Fully-uppercase terms are ACRONYMS: exact case-sensitive word match,
    no plural ('ATE' hits 'ATE' but never 'ate', 'plate' or 'ATES')."""
    t = text or ""
    for term in boost_phrases:
        if term.isupper():
            if re.search(r"\b" + re.escape(term) + r"\b", t):
                return term
            continue
        pat = r"\b" + r"[\s\-]*".join(re.escape(w) for w in term.split()) + r"s?\b"
        if re.search(pat, t, re.IGNORECASE):
            return term
    return None


# ── the two-pass gate ──────────────────────────────────────────────────────────────

def _grams(text: str, stop: set) -> set[str]:
    """Lowercase -> [a-z]{3,} tokens minus stopwords -> unigrams + adjacent bigrams.
    Identical to the miner's grams() — the gate's correctness depends on it."""
    words = [w for w in _TOK.findall((text or "").lower()) if w not in stop]
    out: set[str] = set(words)
    for i in range(len(words) - 1):
        out.add(words[i] + " " + words[i + 1])
    return out


def neg_match(g: set[str], t: Terms) -> list[str] | None:
    """Matched negative terms (sorted) if the negative gate fires, else None. Mirrors
    ``mine_eliminators._eliminates``: a phrase or non-guarded word hits directly; a
    guarded unigram fires only under the two-signal rule (>=2 distinct word hits)."""
    matched = (g & t.neg_phrases) | (g & t.neg_words)
    direct = (g & t.neg_phrases) | (g & (t.neg_words - t.guarded))
    if direct:
        return sorted(matched)
    if (g & t.guarded) and len(g & t.neg_words) >= 2:
        return sorted(matched)
    return None


def pos_hit(text: str, t: Terms) -> bool:
    """High-precision in-scope veto: a substring phrase hit or a word-boundary token hit."""
    tl = (text or "").lower()
    if any(p in tl for p in t.pos_phrases):
        return True
    return bool(set(_POS_TOK_RE.findall(tl)) & t.pos_tokens)


def eliminate(text: str, t: Terms) -> list[str] | None:
    """Two-pass decision. Returns the matched negative terms (sorted) if the bid is
    eliminated (``neg_hit AND NOT pos_hit``), else None (survives -> Haiku)."""
    matched = neg_match(_grams(text, t.stop), t)
    if matched and not pos_hit(text, t):
        return matched
    return None


# ── shadow analysis (no writes; the cutover gate) ──────────────────────────────────

def collision_rows(records, t: Terms, min_score: int = 3) -> list[dict]:
    """The would-eliminate bids whose existing score >= min_score (the cutover risk).
    These are what shadow mode flags for human review before a hard cutover."""
    out = []
    for r in records:
        if r.pass1_score is None or r.pass1_score < min_score:
            continue
        matched = eliminate(r.text, t)
        if matched is not None:
            out.append({"portal": r.portal, "bid_id": r.bid_id, "score": r.pass1_score,
                        "matched": ", ".join(matched), "text": r.text})
    out.sort(key=lambda d: (-d["score"], d["portal"]))
    return out


def shadow_report(records, t: Terms) -> dict:
    """Run the gate over NormalizedRecords WITHOUT writing. Reports would-eliminate
    counts, score>=3 collisions (must be 0 to cut over), and positive-veto saves."""
    total = elim = collisions = vetoed = 0
    for r in records:
        total += 1
        g = _grams(r.text, t.stop)
        neg = neg_match(g, t)
        if neg is None:
            continue
        if pos_hit(r.text, t):
            vetoed += 1
            continue
        elim += 1
        if r.pass1_score is not None and r.pass1_score >= 3:
            collisions += 1
    return {"total": total, "would_eliminate": elim,
            "score_ge3_collisions": collisions, "pos_vetoed": vetoed}

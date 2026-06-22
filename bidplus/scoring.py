"""Shared scoring module (S5) — normalized records + (chunk 2) the Haiku Pass-1 engine.

Decision #9-A: the scorer is portal-agnostic. Each adapter exposes its DB rows as
``NormalizedRecord``s (a common shape) via ``scoring_records()``; this module owns the
eliminator gate (see :mod:`bidplus.eliminator`) and the Pass-1 batch scoring. The only
per-portal scoring code is the thin field map each adapter passes to :func:`read_records`.

``text`` is the single string the gate tokenises and Pass-1 scores — the same column the
offline miner used (HAL/ISRO ``tender_description``, GeM ``items``) so the runtime gram
set matches the mined lists exactly.
"""

from __future__ import annotations

import json
import os
import random
import re
import sqlite3
import time
from dataclasses import dataclass, field

import bidplus.config as config


@dataclass
class NormalizedRecord:
    """A portal row reduced to the common scoring shape."""

    portal: str
    bid_id: str               # '|'-joined primary key (stable id used for 1:1 mapping)
    pk: tuple                 # raw primary-key tuple (for writing scores back)
    text: str                 # title/items — gated + Pass-1-scored
    fields: dict = field(default_factory=dict)  # buyer/value/closing_date/description
    pass1_score: int | None = None              # existing score (shadow analysis)


def read_records(portal: str, db_path: str, spec: dict, where: str = "1=1") -> list[NormalizedRecord]:
    """Read a tool DB (read-only) into NormalizedRecords using a per-portal field map.

    ``spec`` = ``{"table", "pk": (...), "text": col, "fields": {name: col, ...}}``.
    """
    pk = spec["pk"]
    text_col = spec["text"]
    fmap = spec.get("fields", {})
    cols = list(dict.fromkeys([*pk, text_col, *fmap.values(), "pass1_score"]))

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(f"SELECT {', '.join(cols)} FROM {spec['table']} WHERE {where}").fetchall()
    finally:
        conn.close()

    out: list[NormalizedRecord] = []
    for r in rows:
        pkv = tuple(r[c] for c in pk)
        out.append(NormalizedRecord(
            portal=portal,
            bid_id="|".join("" if v is None else str(v) for v in pkv),
            pk=pkv,
            text=r[text_col] or "",
            fields={name: r[col] for name, col in fmap.items()},
            pass1_score=r["pass1_score"],
        ))
    return out


# ════════════════════════════════════════════════════════════════════════════════════
# Pass-1 Haiku engine (S5 chunk 2)
#
# Centralized, portal-agnostic. Robustness lessons from the S2 GeM run (HANDOFF §10.1)
# are baked in: transient API errors are bounded-retried with backoff and NEVER skipped
# to NULL; every submitted bid_id gets exactly one mapped result (missing ids are
# per-item retried, never silently dropped); the legacy duplicate-rationale gate that
# over-fired on similar junk is REMOVED (1:1 id-mapping is the real collapse guard).
# ════════════════════════════════════════════════════════════════════════════════════

PASS1_BATCH = int(os.environ.get("PASS1_BATCH", "25"))         # output-budget-bounded
PASS1_MAX_TOKENS = int(os.environ.get("PASS1_MAX_TOKENS", "8192"))
_TRANSIENT_ATTEMPTS = 5


def _backoff(attempt: int) -> None:
    time.sleep(min(2 ** attempt, 30) + random.uniform(0, 0.5))


def _build_system(cap_ref: str) -> list[dict]:
    # Cache the (large, static) rubric so each batch pays input tokens once.
    return [{"type": "text", "text": cap_ref, "cache_control": {"type": "ephemeral"}}]


def _build_user(records: list[NormalizedRecord]) -> str:
    # Map by the line NUMBER, not the bid_id: a composite PK (HAL tender|line) contains
    # delimiters the model mangles, breaking exact-id echo. An integer index it echoes
    # reliably and is recovered defensively (digits) in _score_batch.
    listing = "\n".join(f"{i+1}. {r.text}" for i, r in enumerate(records))
    return (
        "Score each numbered bid title 0-5 using the rubric above.\n\n"
        f"{listing}\n\n"
        "Return ONLY a JSON array — no prose, one element per numbered item, each with "
        "exactly: id (the item NUMBER as an integer), score (integer 0-5), "
        "confidence (High/Medium/Low), domain (matched core domain name), "
        "rationale (1-2 sentences). These are one-line titles — apply generous leeway; "
        "if the domain could plausibly match, score >=2."
    )


def _raw_haiku(records: list[NormalizedRecord], cap_ref: str) -> str:
    """One Haiku call (no retry). Raises on error; SystemExit on a billing/usage limit."""
    import anthropic  # lazy: keeps the module importable without the SDK / a key

    client = anthropic.Anthropic(api_key=config.require_api_key())
    try:
        resp = client.messages.create(
            model=config.PASS1_MODEL,
            max_tokens=PASS1_MAX_TOKENS,
            system=_build_system(cap_ref),
            messages=[{"role": "user", "content": _build_user(records)}],
        )
        return resp.content[0].text
    except anthropic.APIStatusError as e:
        msg = str(e).lower()
        if getattr(e, "status_code", None) in (400, 429) and any(
            k in msg for k in ("billing", "credit", "spend limit", "usage limit")
        ):
            raise SystemExit("[STOP] Anthropic billing/usage limit reached — halting Pass-1.")
        raise


# Transient error types worth a bounded retry (never a skip-to-NULL).
def _transient_types() -> tuple:
    types: list = [ConnectionError, TimeoutError]
    try:
        import anthropic
        types += [anthropic.APIConnectionError, anthropic.APITimeoutError,
                  anthropic.InternalServerError, anthropic.RateLimitError]
    except Exception:
        pass
    return tuple(types)


def _is_overloaded(exc) -> bool:
    return getattr(exc, "status_code", None) in (429, 503, 529)


def _with_retry(thunk, attempts: int = _TRANSIENT_ATTEMPTS):
    """Run ``thunk`` with bounded retry+backoff on transient failures. Raises on
    exhaustion (caller then leaves the bid unscored for next run — never writes NULL)."""
    transient = _transient_types()
    last = None
    for a in range(attempts):
        try:
            return thunk()
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001 — narrow to transient below
            if isinstance(e, transient) or _is_overloaded(e):
                last = e
                _backoff(a)
                continue
            raise
    raise RuntimeError(f"Pass-1 call failed after {attempts} attempts: {last!r}")


def _parse_array(text: str) -> list[dict]:
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not m:
        return []
    try:
        arr = json.loads(m.group())
        return arr if isinstance(arr, list) else []
    except json.JSONDecodeError:
        return []


def _coerce(res: dict) -> dict:
    digits = re.search(r"\d+", str(res.get("score", "0")))
    score = max(0, min(5, int(digits.group()))) if digits else 0
    return {
        "pass1_score": score,
        "pass1_confidence": str(res.get("confidence", "")),
        "pass1_domain": str(res.get("domain", "")),
        "pass1_rationale": str(res.get("rationale", "")),
    }


def _score_batch(records, cap_ref, call_fn, _retry: bool = False) -> dict:
    """Score one batch. Returns ``{bid_id: coerced}``, mapping the model's echoed line
    NUMBER (1-based, defensively digit-extracted) back to each record. Any numbered item
    the model omits is recovered by a 1-item retry — never silently dropped."""
    text = _with_retry(lambda: call_fn(records, cap_ref))
    rmap: dict[str, dict] = {}
    for d in _parse_array(text):
        m = re.search(r"\d+", str(d.get("id", "")))
        if m:
            rmap[m.group()] = d

    scored: dict = {}
    missing = []
    for i, r in enumerate(records):
        d = rmap.get(str(i + 1))
        if d is None:
            missing.append(r)
        else:
            scored[r.bid_id] = _coerce(d)

    if not _retry:
        for r in missing:  # per-item recovery (bounded: _retry=True won't recurse)
            scored.update(_score_batch([r], cap_ref, call_fn, _retry=True))
    return scored


def score_records(records, cap_ref, call_fn=None, batch_size: int | None = None) -> dict:
    """Batch-score NormalizedRecords. Returns ``{bid_id: {pass1_score, ...}}``. A bid the
    engine cannot score (persistent failure) is simply absent → caller leaves it NULL for
    the next run (re-queue), never a fabricated 0."""
    call_fn = call_fn or _raw_haiku
    batch_size = batch_size or PASS1_BATCH
    scored: dict = {}
    for i in range(0, len(records), batch_size):
        scored.update(_score_batch(records[i:i + batch_size], cap_ref, call_fn))
    return scored


# ── persistence + per-portal orchestration ────────────────────────────────────────

def ensure_scoring_columns(conn: sqlite3.Connection, table: str) -> None:
    """Additively add the S5 provenance columns to a tool bids table."""
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    for col, decl in (("pass1_method", "TEXT"), ("pass1_eliminated_by", "TEXT"),
                      ("auto_rejected", "INTEGER DEFAULT 0")):
        if col not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def score_portal(portal: str, parent: sqlite3.Connection, mode: str = "hard",
                 limit: int | None = None, rescore: bool = False,
                 call_fn=None) -> dict:
    """Run the eliminator gate + Haiku Pass-1 for one portal, writing scores to its tool DB.

    mode='hard' (default, post-cutover): eliminated bids get score 0 + pass1_method='keyword'
    and skip Haiku. mode='shadow': would-eliminate bids are logged but STILL sent to Haiku
    (no keyword writes). Survivors are model-scored (pass1_method='model'). A human-PROMOTED
    bid bypasses the eliminator (always Haiku) — a confirmed in-scope bid is never re-eliminated.
    Only NULL-score bids are picked up unless rescore=True.
    """
    from bidplus import eliminator, governance, runtime
    from bidplus.adapters.gem import GeMAdapter
    from bidplus.adapters.hal import HALAdapter
    from bidplus.adapters.halc import HALCAdapter
    from bidplus.adapters.isro import ISROAdapter

    adapter = {"hal": HALAdapter, "halc": HALCAdapter, "isro": ISROAdapter, "gem": GeMAdapter}[portal]()
    spec = adapter._SCORING
    table, pk = spec["table"], spec["pk"]
    eliminator.ensure_boost_seed(parent)
    eliminator.ensure_inscope_seed(parent)
    terms = eliminator.load_terms(parent)
    promoted = governance.promoted_bid_ids(parent, portal)
    cap_ref = runtime.capability_reference_path().read_text()

    where = "1=1" if rescore else "pass1_score IS NULL"
    records = adapter.scoring_records(where)
    if limit:
        records = records[:limit]

    # Boost-matched bids bypass the eliminator and are forced to score 5 after Haiku.
    boosted: dict[str, str] = {}
    for r in records:
        term = eliminator.boost_match(r.text, terms.boost_phrases)
        if term:
            boosted[r.bid_id] = term

    survivors, eliminated, would = [], [], 0
    for r in records:
        if r.bid_id in promoted or r.bid_id in boosted:   # confirmed in-scope → always Haiku
            survivors.append(r)
            continue
        matched = eliminator.eliminate(r.text, terms)
        if matched is not None:
            would += 1
            if mode == "hard":
                eliminated.append((r, matched))
                continue
        survivors.append(r)

    scored = score_records(survivors, cap_ref, call_fn=call_fn)

    conn = sqlite3.connect(adapter.tool_db_path())
    try:
        ensure_scoring_columns(conn, table)
        pk_where = " AND ".join(f"{c}=?" for c in pk)
        model_n = 0
        unscored_ids = []
        for r in survivors:
            res = scored.get(r.bid_id)
            if res is None:
                unscored_ids.append(r.bid_id)
                continue  # left NULL, re-queued next run (never a fake 0)
            score, rationale = res["pass1_score"], res["pass1_rationale"]
            if r.bid_id in boosted:
                score = 5
                rationale = f"[auto-promoted: {boosted[r.bid_id]}] {rationale or ''}".strip()
            conn.execute(
                f"UPDATE {table} SET pass1_score=?, pass1_confidence=?, pass1_domain=?, "
                f"pass1_rationale=?, pass1_method='model', pass1_eliminated_by=NULL, "
                f"auto_rejected=0 WHERE {pk_where}",
                (score, res["pass1_confidence"], res["pass1_domain"],
                 rationale, *r.pk),
            )
            model_n += 1
        for r, matched in eliminated:
            conn.execute(
                f"UPDATE {table} SET pass1_score=0, pass1_confidence='High', "
                f"pass1_domain='N/A', pass1_rationale=?, pass1_method='keyword', "
                f"pass1_eliminated_by=?, auto_rejected=1 WHERE {pk_where}",
                (f"keyword-eliminated: {', '.join(matched)}", ", ".join(matched), *r.pk),
            )
        conn.commit()
    finally:
        conn.close()

    return {"portal": portal, "mode": mode, "candidates": len(records),
            "would_eliminate": would, "model_scored": model_n,
            "keyword_eliminated": len(eliminated), "boosted": len(boosted),
            "unscored_left": len(survivors) - model_n,
            "unscored_ids": unscored_ids}

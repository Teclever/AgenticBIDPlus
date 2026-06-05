import functools
import json
import re
import sys
import time
from typing import Callable

import anthropic

from config import ANTHROPIC_API_KEY, PASS1_BATCH_SIZE, PASS1_MODEL
from modules.db import get_few_shot_examples

# ── client (lazy) ─────────────────────────────────────────────────────────────

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


# ── few-shot cache ────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def _cached_few_shots() -> str:
    """Build and cache few-shot calibration text for the system prompt.

    Cached for the process lifetime — examples are loaded once per run.
    """
    rows = get_few_shot_examples()
    if not rows:
        return ""
    lines = ["## Calibration Examples", ""]
    for i, row in enumerate(rows, 1):
        lines.append(
            f"{i}. Title: {row['tender_title']} "
            f"→ Score: {row['correct_score']} | Reason: {row['reason']}"
        )
    return "\n".join(lines)


# ── prompt builders ───────────────────────────────────────────────────────────

def build_system_prompt(capability_ref: str) -> list[dict]:
    """Return the Anthropic system content block list with cache_control: ephemeral.

    The capability reference + any calibration examples are combined into a
    single cacheable block to minimise repeated prompt-token charges.
    """
    few_shots = _cached_few_shots()
    text = capability_ref
    if few_shots:
        text = text + "\n\n" + few_shots
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def build_pass1_prompt(tenders: list[dict]) -> str:
    """Format a batch of tenders as a numbered list for the Pass 1 API call."""
    header = (
        f"Score the following {len(tenders)} tender(s) against the capability reference above.\n\n"
        "Return a JSON array — one object per tender — with exactly these fields:\n"
        '  "tender_number"  : string\n'
        '  "line_number"    : string\n'
        '  "score"          : integer 0–5\n'
        '  "confidence"     : "High" | "Medium" | "Low"\n'
        '  "domain"         : closest Core Domain name\n'
        '  "matching_tech"  : comma-separated matched technologies/standards, or "None"\n'
        '  "rationale"      : 2–3 sentences citing specific evidence\n'
        '  "gaps"           : missing capability/tech, or "None"\n'
        '  "recommendation" : "PURSUE" | "PURSUE WITH RAMP-UP" | "ASSESS FURTHER" | "DECLINE"\n'
        "                     (mapping: PURSUE=score 4–5, PURSUE WITH RAMP-UP=score 3, "
        "ASSESS FURTHER=score 2, DECLINE=score 0–1)\n\n"
        "Return ONLY the JSON array. No markdown fences. No other text.\n\n"
        "TENDERS:"
    )
    lines = [header]
    for i, t in enumerate(tenders, 1):
        lines.append(
            f"{i}. [{t.get('tender_number', '?')} | LN:{t.get('line_number', '?')}] "
            f"{t.get('tender_description', '(no description)')} | "
            f"Buyer: {t.get('buyer', '?')} | "
            f"Region: {t.get('tender_region', '?')} | "
            f"Est. Cost: {t.get('estimated_cost', '?')} | "
            f"EMD: {t.get('emd_listing', '?')} | "
            f"Closes: {t.get('closing_date', '?')} | "
            f"Bidder: {t.get('bidder_type', '?')}"
        )
    return "\n".join(lines)


# ── API call ──────────────────────────────────────────────────────────────────

def _call_api(tenders: list[dict], capability_ref: str) -> str | None:
    """Call Haiku with a batch of tenders. Returns response text or None on transient error.

    Exits the process on billing/permission errors — there is no safe recovery.
    """
    system = build_system_prompt(capability_ref)
    prompt = build_pass1_prompt(tenders)
    client = _get_client()

    try:
        resp = client.messages.create(
            model=PASS1_MODEL,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    except anthropic.OverloadedError:
        print("  [pass1] API overloaded (529) — skipping batch", flush=True)
        return None
    except anthropic.RateLimitError:
        print("  [pass1] Rate limit (429) — waiting 30s then retrying once", flush=True)
        time.sleep(30)
        try:
            resp = client.messages.create(
                model=PASS1_MODEL,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text
        except Exception:
            return None
    except anthropic.PermissionDeniedError as e:
        print(f"\n[pass1] Billing limit reached — cannot continue: {e}", file=sys.stderr)
        sys.exit(1)
    except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
        print(f"  [pass1] Connection error — skipping batch: {e}", flush=True)
        return None


# ── response parser ───────────────────────────────────────────────────────────

def _parse_json_results(text: str) -> list[dict]:
    """Extract the JSON array from the model response.

    Handles clean JSON, markdown-fenced JSON, and responses with preamble text.
    """
    if not text:
        return []

    # Strip markdown code fences if present
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)

    # Find first [ ... ] array
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []

    try:
        results = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []

    if not isinstance(results, list):
        return []

    cleaned = []
    for item in results:
        if not isinstance(item, dict):
            continue
        try:
            cleaned.append({
                "tender_number": str(item.get("tender_number", "")),
                "line_number":   str(item.get("line_number", "")),
                "score":         int(item.get("score", 0)),
                "confidence":    str(item.get("confidence", "Low")),
                "domain":        str(item.get("domain", "")),
                "matching_tech": str(item.get("matching_tech", "")),
                "rationale":     str(item.get("rationale", "")),
                "gaps":          str(item.get("gaps", "")),
                "recommendation": str(item.get("recommendation", "")),
            })
        except (TypeError, ValueError):
            continue

    return cleaned


# ── validation gates ──────────────────────────────────────────────────────────

def _validate_all_ids_present(
    tenders: list[dict], result_map: dict[tuple, dict]
) -> list[dict]:
    """Gate 1: Return the subset of tenders whose IDs are missing from the result map."""
    missing = []
    for t in tenders:
        key = (t.get("tender_number", ""), t.get("line_number", ""))
        if key not in result_map:
            missing.append(t)
    return missing


def _validate_no_identical_rationales(
    tenders: list[dict], results: list[dict], result_map: dict[tuple, dict]
) -> list[dict]:
    """Gate 2: Return tenders whose scored entry has the same rationale as an adjacent entry.

    Adjacent = consecutive in the original tenders list. Both members of each
    identical pair are flagged for individual retry.
    """
    # Build ordered list of scored results in input order
    ordered = []
    for t in tenders:
        key = (t.get("tender_number", ""), t.get("line_number", ""))
        if key in result_map:
            ordered.append((t, result_map[key]))

    flagged = set()
    for i in range(len(ordered) - 1):
        r_cur  = ordered[i][1]["rationale"].strip()
        r_next = ordered[i + 1][1]["rationale"].strip()
        if r_cur and r_cur == r_next:
            flagged.add(i)
            flagged.add(i + 1)

    return [ordered[i][0] for i in sorted(flagged)]


# ── individual retry ──────────────────────────────────────────────────────────

def _retry_individually(tenders: list[dict], capability_ref: str) -> list[dict]:
    """Score each tender one at a time as a fallback for gate failures."""
    results = []
    for t in tenders:
        text = _call_api([t], capability_ref)
        if not text:
            continue
        parsed = _parse_json_results(text)
        if parsed:
            results.append(parsed[0])
    return results


# ── batch orchestrator ────────────────────────────────────────────────────────

def score_bids_batch(tenders: list[dict], capability_ref: str) -> list[dict]:
    """Score one batch (≤25) through the two-gate pipeline.

    Gate failures trigger individual retries for the affected tenders only.
    Returns the merged, deduplicated scored list.
    """
    text = _call_api(tenders, capability_ref)
    initial = _parse_json_results(text) if text else []

    result_map: dict[tuple, dict] = {
        (r["tender_number"], r["line_number"]): r for r in initial
    }

    # Gate 1: missing IDs
    missing = _validate_all_ids_present(tenders, result_map)
    if missing:
        print(
            f"  [pass1] Gate 1: {len(missing)} missing IDs — retrying individually",
            flush=True,
        )
        for r in _retry_individually(missing, capability_ref):
            result_map[(r["tender_number"], r["line_number"])] = r

    # Gate 2: identical consecutive rationales
    dupes = _validate_no_identical_rationales(tenders, initial, result_map)
    if dupes:
        print(
            f"  [pass1] Gate 2: {len(dupes)} duplicate-rationale entries — retrying individually",
            flush=True,
        )
        for r in _retry_individually(dupes, capability_ref):
            result_map[(r["tender_number"], r["line_number"])] = r

    return list(result_map.values())


# ── bulk entry point ──────────────────────────────────────────────────────────

def score_bids_pass1_bulk(
    tenders: list[dict],
    capability_ref: str,
    on_batch: Callable[[list[dict]], None] | None = None,
) -> list[dict]:
    """Score all tenders in batches of PASS1_BATCH_SIZE.

    Calls on_batch(scored_batch) after each batch completes.
    Returns the full list of scored results.
    """
    all_scored: list[dict] = []
    total = len(tenders)

    for start in range(0, total, PASS1_BATCH_SIZE):
        batch = tenders[start: start + PASS1_BATCH_SIZE]
        batch_num = start // PASS1_BATCH_SIZE + 1
        total_batches = (total + PASS1_BATCH_SIZE - 1) // PASS1_BATCH_SIZE
        print(
            f"  [pass1] Batch {batch_num}/{total_batches} "
            f"({len(batch)} tenders, {start + 1}–{start + len(batch)} of {total})",
            flush=True,
        )
        scored = score_bids_batch(batch, capability_ref)
        all_scored.extend(scored)
        if on_batch:
            on_batch(scored)

    return all_scored

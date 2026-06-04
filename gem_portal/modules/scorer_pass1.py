import re, sys, json, anthropic
from modules.db import get_exclusion_rules, get_few_shot_examples
from functools import lru_cache


@lru_cache(maxsize=1)
def _cached_few_shots() -> tuple:
    """Cache few-shot examples for the duration of the process — DB doesn't change mid-run."""
    return tuple(get_few_shot_examples())

BATCH_SIZE = 25


def check_exclusion(items: str, rules: list[dict]) -> str | None:
    """Returns matching rule reason if bid should be excluded, else None."""
    title_lower = items.lower()
    for rule in rules:
        if rule["pattern"].lower() in title_lower:
            return rule["reason"]
    return None


def build_system(capability_ref: str, few_shots: list[dict]) -> list[dict]:
    """
    Combine capability_ref and few-shot examples into a single cached system block.
    Returns the system parameter as a list with cache_control set.
    """
    examples_text = ""
    if few_shots:
        examples_text = "\n\n---\n## Calibration examples from human feedback\n"
        for ex in few_shots[:8]:
            examples_text += (
                f"\nBid title: \"{ex['bid_title']}\"\n"
                f"Correct score: {ex['correct_score']}\n"
                f"Reason: {ex['reason']}\n"
            )

    combined = capability_ref + examples_text
    return [{"type": "text", "text": combined, "cache_control": {"type": "ephemeral"}}]


def build_pass1_prompt(items: str) -> list[dict]:
    """Build messages list with bid title only as user content."""
    user_content = (
        f"Score this bid title using the rubric above.\n\n"
        f"Bid title: \"{items}\"\n\n"
        f"Note: This is a one-liner title only. Apply generous leeway — "
        f"do not penalise for missing technical detail. If the domain could "
        f"plausibly match, score it 2 or above."
    )
    return [{"role": "user", "content": user_content}]


def parse_score_response(text: str) -> dict:
    """Extract structured fields from Haiku response."""
    def extract(label: str) -> str:
        m = re.search(rf"{label}:\s*(.+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    score_raw = extract("SCORE") or "0"
    score_digits = re.search(r'\d+', score_raw)
    return {
        "pass1_score":       int(score_digits.group()) if score_digits else 0,
        "pass1_confidence":  extract("CONFIDENCE"),
        "pass1_domain":      extract("DOMAIN MATCH"),
        "pass1_rationale":   extract("RATIONALE"),
        "pass1_gaps":        extract("GAPS"),
    }


def _parse_json_results(text: str) -> list[dict]:
    """Extract JSON array from model response. Returns empty list on failure."""
    try:
        m = re.search(r'\[.*\]', text, re.DOTALL)
        return json.loads(m.group()) if m else []
    except (json.JSONDecodeError, AttributeError):
        return []


def _apply_result_map(bids: list[dict], result_map: dict) -> list[dict]:
    """Merge result_map scores into bid dicts. Missing bid_numbers get zeroes."""
    scored = []
    for bid in bids:
        r = result_map.get(str(bid["bid_number"]), {})
        score_raw = str(r.get("score", "0"))
        score_digits = re.search(r'\d+', score_raw)
        bid.update({
            "pass1_score":      int(score_digits.group()) if score_digits else 0,
            "pass1_confidence": str(r.get("confidence", "")),
            "pass1_domain":     str(r.get("domain", "")),
            "pass1_rationale":  str(r.get("rationale", "")),
            "pass1_gaps":       "",
            "exclusion_matched": None,
        })
        scored.append(bid)
    return scored


def _call_api(bids: list[dict], capability_ref: str) -> str | None:
    """
    Make a single API call for the given bids.
    Returns response text on success, None if overloaded/connection error.
    Exits on billing limit.
    """
    from config import ANTHROPIC_API_KEY

    numbered = "\n".join(
        f"{i+1}. bid_number={bid['bid_number']} | title={bid.get('items', '')}"
        for i, bid in enumerate(bids)
    )
    user_content = (
        f"Score each of the following bid titles using the rubric above.\n\n"
        f"{numbered}\n\n"
        f"Return a JSON array only — no other text. Each element must have exactly "
        f"these fields: bid_number, score (integer 0-5), confidence (High/Medium/Low), "
        f"domain (matched Core Domain name), rationale (1-2 sentences).\n"
        f"Note: These are one-liner titles only. Apply generous leeway — "
        f"do not penalise for missing technical detail."
    )

    few_shots = list(_cached_few_shots())
    system = build_system(capability_ref, few_shots)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=8192,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text
    except anthropic.APIStatusError as e:
        if e.status_code == 529:
            print(f"  [warn] Anthropic API overloaded — skipping batch of {len(bids)}")
            return None
        err_str = str(e).lower()
        if e.status_code in (400, 429) and ("billing" in err_str or "usage limit" in err_str or "spend limit" in err_str):
            print("[STOP] Monthly spend limit reached — halting run.")
            sys.exit(1)
        raise
    except anthropic.APIConnectionError:
        print(f"  [warn] Connection error — skipping batch of {len(bids)}")
        return None


def score_bids_batch(bids: list[dict], capability_ref: str,
                     _retry_mode: bool = False) -> list[dict]:
    """
    Score a batch of up to BATCH_SIZE bids in a single API call.

    Write gate — before writing any result, the response must pass:
      1. All input bid_numbers present in the response (not just count match).
         Failure triggers per-bid retry.
      2. No two consecutive scored bids share identical rationale text.
         Flagged pairs are retried individually.

    _retry_mode=True disables the write gate to prevent infinite recursion
    when called for individual bids.
    """
    text = _call_api(bids, capability_ref)
    if text is None:
        return bids  # API unavailable — return unscored, caller handles

    results = _parse_json_results(text)
    result_map = {str(r.get("bid_number", "")): r for r in results}

    # Gate 1: all input bid_numbers must be present in the response
    if not _retry_mode:
        input_ids = {str(b["bid_number"]) for b in bids}
        missing = input_ids - set(result_map.keys())
        if missing:
            print(f"  [warn] Response missing {len(missing)}/{len(bids)} bid(s) "
                  f"— retrying individually")
            return _retry_individually(bids, capability_ref)

    scored = _apply_result_map(bids, result_map)

    # Gate 2: consecutive identical rationales indicate response collapse
    if not _retry_mode:
        flagged = set()
        for i in range(1, len(scored)):
            r_prev = scored[i - 1].get("pass1_rationale", "")
            r_curr = scored[i].get("pass1_rationale", "")
            if r_prev and r_curr and r_prev == r_curr:
                print(f"  [warn] Identical rationale on consecutive bids "
                      f"{scored[i-1]['bid_number']} / {scored[i]['bid_number']} "
                      f"— retrying individually")
                flagged.add(i - 1)
                flagged.add(i)

        if flagged:
            flagged_bids   = [bids[i]   for i in sorted(flagged)]
            retried        = _retry_individually(flagged_bids, capability_ref)
            retried_map    = {b["bid_number"]: b for b in retried}
            for i in sorted(flagged):
                bn = bids[i]["bid_number"]
                if bn in retried_map:
                    scored[i] = retried_map[bn]

    return scored


def _retry_individually(bids: list[dict], capability_ref: str) -> list[dict]:
    """Score each bid in a separate API call. Used as fallback after gate failure."""
    results = []
    for bid in bids:
        result = score_bids_batch([bid], capability_ref, _retry_mode=True)
        results.extend(result)
    return results


def score_bid_pass1(bid: dict, capability_ref: str) -> dict:
    """
    Single-bid entry point (used by run_pipeline2 and other callers).
    Hits exclusion filter, then scores via a one-item batch call.
    """
    rules = get_exclusion_rules()
    exclusion_hit = check_exclusion(bid.get("items", ""), rules)

    if exclusion_hit:
        bid.update({
            "pass1_score": 0,
            "pass1_confidence": "High",
            "pass1_domain": "N/A",
            "pass1_rationale": f"Excluded by pattern rule: {exclusion_hit}",
            "pass1_gaps": "N/A",
            "exclusion_matched": exclusion_hit,
        })
        return bid

    return score_bids_batch([bid], capability_ref)[0]


def score_bids_pass1_bulk(bids: list[dict], capability_ref: str,
                           on_batch=None) -> list[dict]:
    """
    Bulk entry point: applies exclusion filter, then scores remaining bids
    in batches of BATCH_SIZE. Calls on_batch(chunk) after each batch so the
    caller can persist scores immediately — resumable on crash.
    Returns all bids (excluded + scored).
    """
    rules = get_exclusion_rules()
    excluded = []
    to_score = []

    for bid in bids:
        exclusion_hit = check_exclusion(bid.get("items", ""), rules)
        if exclusion_hit:
            bid.update({
                "pass1_score": 0,
                "pass1_confidence": "High",
                "pass1_domain": "N/A",
                "pass1_rationale": f"Excluded by pattern rule: {exclusion_hit}",
                "pass1_gaps": "N/A",
                "exclusion_matched": exclusion_hit,
            })
            excluded.append(bid)
        else:
            to_score.append(bid)

    if excluded:
        if on_batch:
            on_batch(excluded)
        print(f"  {len(excluded)} excluded by rules (no LLM call), "
              f"{len(to_score)} remaining to score via LLM...")

    all_scored = list(excluded)
    for i in range(0, len(to_score), BATCH_SIZE):
        chunk = to_score[i:i + BATCH_SIZE]
        scored_chunk = score_bids_batch(chunk, capability_ref)
        if on_batch:
            on_batch(scored_chunk)
        all_scored.extend(scored_chunk)
        print(f"  {min(i + BATCH_SIZE, len(to_score))}/{len(to_score)} LLM-scored "
              f"({len(excluded)} excluded, {len(excluded) + min(i + BATCH_SIZE, len(to_score))} total done)...")

    return all_scored

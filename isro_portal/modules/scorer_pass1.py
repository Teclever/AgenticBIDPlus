"""Pass 1 scoring — fast, cheap, title/summary-level triage via Anthropic.

Scores unscored tenders 0-5 in batches of `PASS1_BATCH_SIZE` using the Haiku
model. Hardened against malformed LLM JSON: tolerant parsing, a gate that every
input `tender_id` is present in the response, batch retries, and a per-bid
fallback so one bad batch never blocks the run. `on_batch` is invoked after each
chunk so the caller can persist immediately (resumable).
"""

from __future__ import annotations

import json
import os
import re
from typing import Callable

import anthropic

from config import PASS1_BATCH_SIZE, PASS1_MODEL

MAX_BATCH_RETRIES = 2


def score_bids_pass1_bulk(
    bids: list[dict],
    capability_reference: str,
    on_batch: Callable[[list[dict]], None],
) -> None:
    if not bids:
        return
    client = _client()
    total = len(bids)
    total_batches = (total + PASS1_BATCH_SIZE - 1) // PASS1_BATCH_SIZE
    print(f"  Pass1 queue: {total} bid(s) in {total_batches} batch(es) of {PASS1_BATCH_SIZE}.")

    for batch_idx, i in enumerate(range(0, total, PASS1_BATCH_SIZE), start=1):
        chunk = bids[i : i + PASS1_BATCH_SIZE]
        start = i + 1
        end = min(i + len(chunk), total)
        print(f"  [batch {batch_idx}/{total_batches}] scoring bids {start}-{end} (size={len(chunk)})")
        scored = _score_chunk_with_retries(
            client=client,
            bids=chunk,
            cap_ref=capability_reference,
            batch_idx=batch_idx,
            total_batches=total_batches,
        )
        on_batch(scored)
        done = end
        print(f"  [batch {batch_idx}/{total_batches}] done ({done}/{total} processed)")


def _score_chunk(client: anthropic.Anthropic, bids: list[dict], cap_ref: str) -> list[dict]:
    payload = [
        {
            "tender_id": b["tender_id"],
            "center_name": b.get("center_name", ""),
            "tender_description": b.get("tender_description", ""),
            "detail_text": (b.get("detail_text") or "")[:1200],
        }
        for b in bids
    ]
    prompt = (
        "Score each ISRO tender from 0 to 5 for Teclever fit.\n"
        "Return strict JSON list with fields: "
        "tender_id, score, confidence, domain, rationale, gaps.\n\n"
        f"Capability reference:\n{cap_ref}\n\n"
        f"Tenders JSON:\n{json.dumps(payload, ensure_ascii=True)}"
    )
    try:
        msg = client.messages.create(
            model=PASS1_MODEL,
            max_tokens=5000,
            temperature=0,
            system="You are a strict procurement scoring engine. Return only valid JSON.",
            messages=[{"role": "user", "content": prompt}],
        )
        parsed = _extract_json(msg.content[0].text)
        by_id = {x.get("tender_id"): x for x in parsed if x.get("tender_id")}
        missing = [b["tender_id"] for b in bids if b["tender_id"] not in by_id]
        if missing:
            raise ValueError(f"response missing {len(missing)}/{len(bids)} tender_id values")
        output = []
        for b in bids:
            item = by_id.get(b["tender_id"], {})
            output.append(
                {
                    "tender_id": b["tender_id"],
                    "pass1_score": _clamp_score(item.get("score")),
                    "pass1_confidence": str(item.get("confidence") or "Low"),
                    "pass1_domain": str(item.get("domain") or "Unknown"),
                    "pass1_rationale": str(item.get("rationale") or "No rationale returned."),
                    "pass1_gaps": str(item.get("gaps") or ""),
                }
            )
        return output
    except Exception as exc:
        raise RuntimeError(f"batch call failed: {exc}") from exc


def _score_chunk_with_retries(
    client: anthropic.Anthropic,
    bids: list[dict],
    cap_ref: str,
    batch_idx: int,
    total_batches: int,
) -> list[dict]:
    for attempt in range(1, MAX_BATCH_RETRIES + 2):
        try:
            print(f"    attempt {attempt}/{MAX_BATCH_RETRIES + 1}")
            return _score_chunk(client, bids, cap_ref)
        except Exception as exc:
            text = str(exc)
            parse_like_error = any(
                token in text for token in ["Expecting ", "Unterminated string", "JSON", "tender_id values"]
            )
            if parse_like_error and attempt >= 2:
                print(f"    switching to per-bid fallback due to repeated parse issues: {exc}")
                return _retry_individually(client, bids, cap_ref)
            if attempt <= MAX_BATCH_RETRIES:
                print(f"    retrying batch due to error: {exc}")
                continue
            print(f"    batch failed after retries: {exc}")
            print(f"    falling back to per-bid scoring for batch {batch_idx}/{total_batches}")
            return _retry_individually(client, bids, cap_ref)


def _retry_individually(client: anthropic.Anthropic, bids: list[dict], cap_ref: str) -> list[dict]:
    output: list[dict] = []
    for idx, bid in enumerate(bids, start=1):
        bid_id = bid.get("tender_id", f"row-{idx}")
        for attempt in range(1, MAX_BATCH_RETRIES + 2):
            try:
                print(f"      [fallback {idx}/{len(bids)}] {bid_id} attempt {attempt}/{MAX_BATCH_RETRIES + 1}")
                output.extend(_score_chunk(client, [bid], cap_ref))
                break
            except Exception as exc:
                if attempt <= MAX_BATCH_RETRIES:
                    continue
                print(f"      [fallback {idx}/{len(bids)}] {bid_id} failed: {exc}")
                output.append(_fallback_item(bid))
    return output


def _fallback_item(bid: dict) -> dict:
    return {
        "tender_id": bid["tender_id"],
        "pass1_score": None,
        "pass1_confidence": "Low",
        "pass1_domain": "Unknown",
        "pass1_rationale": "Scoring failed; will retry in a later run.",
        "pass1_gaps": "API or parse failure",
    }


def _extract_json(text: str):
    cleaned = _strip_code_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end != -1 and end > start:
        fragment = cleaned[start : end + 1]
        try:
            return json.loads(fragment)
        except json.JSONDecodeError:
            pass

    # Final attempt: remove problematic ASCII control chars.
    sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", cleaned)
    return json.loads(sanitized)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("\n", 1)
        text = parts[1] if len(parts) > 1 else ""
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _clamp_score(value) -> int | None:
    try:
        s = int(value)
    except Exception:
        return None
    return max(0, min(5, s))


def _client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=api_key)

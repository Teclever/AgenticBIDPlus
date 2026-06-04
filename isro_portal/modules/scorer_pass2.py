"""Pass 2 scoring — deep, per-tender analysis via Anthropic.

For a single shortlisted tender: downloads all document links (and best-effort
nested links found inside extracted text), extracts PDF text (pdfplumber, with a
pypdf fallback), and asks the Sonnet model for a score plus a recommendation
(PURSUE / PURSUE WITH RAMP-UP / ASSESS FURTHER / DECLINE). `set_pass2_attempted`
is called first so flaky downloads/API calls never cause infinite retries.
Downloads are saved under `downloads/<date>/<tender_id>/`.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import anthropic
import pdfplumber
import requests
from pypdf import PdfReader

from config import DOWNLOADS_DIR, PASS2_MODEL, REQUEST_TIMEOUT_SECONDS, USER_AGENT
from modules.db import set_pass2_attempted
from modules.logutil import log_step


def score_bid_pass2(bid: dict, capability_reference: str) -> dict | None:
    tender_id = bid["tender_id"]
    set_pass2_attempted(tender_id)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    links = _collect_links(bid)
    log_step(f"{tender_id}: downloading {len(links)} document link(s)…")
    docs_dir = DOWNLOADS_DIR / _today() / _safe_name(tender_id)
    docs_dir.mkdir(parents=True, exist_ok=True)
    texts: list[str] = []

    for idx, url in enumerate(links, start=1):
        target = docs_dir / f"doc_{idx}{_suffix(url)}"
        raw = _download_file(session, url, target)
        if not raw:
            continue
        if target.suffix.lower() == ".pdf":
            txt = _extract_pdf_text(target)
        else:
            txt = raw.decode("utf-8", errors="ignore")
        if txt:
            texts.append(f"[Document {idx}] {url}\n{txt[:20000]}")

        # Best-effort nested link retrieval from extracted text.
        nested = _extract_urls(txt)[:3]
        for n_idx, nurl in enumerate(nested, start=1):
            n_target = docs_dir / f"nested_{idx}_{n_idx}{_suffix(nurl)}"
            n_raw = _download_file(session, nurl, n_target)
            if not n_raw:
                continue
            n_txt = _extract_pdf_text(n_target) if n_target.suffix.lower() == ".pdf" else n_raw.decode("utf-8", errors="ignore")
            if n_txt:
                texts.append(f"[LinkedDoc {idx}.{n_idx}] {nurl}\n{n_txt[:10000]}")

    if not texts:
        log_step(f"{tender_id}: no extractable text from documents")
        return None

    log_step(f"{tender_id}: calling Anthropic Pass 2 ({PASS2_MODEL})…")
    client = _client()
    payload = {
        "tender_id": tender_id,
        "center_name": bid.get("center_name", ""),
        "tender_description": bid.get("tender_description", ""),
        "pass1_score": bid.get("pass1_score"),
        "detail_text": (bid.get("detail_text") or "")[:4000],
    }
    prompt = (
        "Score this ISRO tender after reviewing all provided documents.\n"
        "Return strict JSON object with fields: score, confidence, domain, rationale, gaps, recommendation.\n"
        "Recommendation must be one of PURSUE, PURSUE WITH RAMP-UP, ASSESS FURTHER, DECLINE.\n\n"
        f"Capability reference:\n{capability_reference}\n\n"
        f"Bid metadata:\n{json.dumps(payload, ensure_ascii=True)}\n\n"
        f"Documents:\n{'\n\n'.join(texts)}"
    )
    try:
        msg = client.messages.create(
            model=PASS2_MODEL,
            max_tokens=3000,
            temperature=0,
            system="You are a strict procurement analysis engine. Return only valid JSON.",
            messages=[{"role": "user", "content": prompt}],
        )
        parsed = _extract_json(msg.content[0].text)
        rec = str(parsed.get("recommendation") or "ASSESS FURTHER").upper()
        if rec not in {"PURSUE", "PURSUE WITH RAMP-UP", "ASSESS FURTHER", "DECLINE"}:
            rec = "ASSESS FURTHER"
        return {
            "pass2_score": _clamp_score(parsed.get("score")),
            "pass2_confidence": str(parsed.get("confidence") or "Low"),
            "pass2_domain": str(parsed.get("domain") or "Unknown"),
            "pass2_rationale": str(parsed.get("rationale") or ""),
            "pass2_gaps": str(parsed.get("gaps") or ""),
            "pass2_recommendation": rec,
        }
    except Exception:
        return None


def _collect_links(bid: dict) -> list[str]:
    links: list[str] = []
    for x in (bid.get("document_url"), bid.get("corrigendum_url")):
        if x:
            links.append(x)
    try:
        parsed = json.loads(bid.get("doc_links_json") or "[]")
        for x in parsed:
            if isinstance(x, str):
                links.append(x)
    except Exception:
        pass
    out: list[str] = []
    seen: set[str] = set()
    for link in links:
        if link not in seen:
            seen.add(link)
            out.append(link)
    return out


def _download_file(session: requests.Session, url: str, target: Path) -> bytes | None:
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        target.write_bytes(resp.content)
        return resp.content
    except Exception:
        return None


def _extract_pdf_text(path: Path) -> str:
    try:
        with pdfplumber.open(path) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
            if text.strip():
                return text
    except Exception:
        pass
    try:
        reader = PdfReader(str(path))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        return ""


def _extract_urls(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r"https?://[^\s)>\"]+", text)


def _suffix(url: str) -> str:
    path = urlparse(url).path.lower()
    if path.endswith(".pdf"):
        return ".pdf"
    if path.endswith(".html") or path.endswith(".htm"):
        return ".html"
    return ".bin"


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")


def _extract_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
    return json.loads(text)


def _clamp_score(value) -> int | None:
    try:
        s = int(value)
    except Exception:
        return None
    return max(0, min(5, s))


def _today() -> str:
    from datetime import date

    return date.today().isoformat()


def _client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=api_key)

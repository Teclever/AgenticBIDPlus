"""S6 Channel 3 — the single path to Sonnet (§8b summarization module).

Given a bid it: (1) ensures docs are fetched + locally extracted (Channels 1–2); (2) if the
bid is a LOCALLY-detected single-vendor / single-tender, records that WITHOUT an LLM call
(GeM-style — saves tokens on a bid whose outcome is already decided); (3) otherwise sends the
pre-cleaned relevant TEXT + any whole scan/image files to Sonnet 4.6 with a strict
structured-extraction prompt; (4) Pydantic-validates the JSON (bounded retry → 'failed'); (5)
persists the validated summary_json (+ provenance) to the parent DB. THE DB STORES ONLY THIS
SUMMARY — extracted text/images live in the per-bid folder, not the DB.

Score 5 runs this automatically; score 4 only extracts (no Sonnet) until a user click.
"""

from __future__ import annotations

import base64
import datetime
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

import bidplus.config as config
from bidplus import extraction

_ADAPTER_PK = {"hal": ("tender_number", "line_number"), "isro": ("tender_id",), "gem": ("bid_number",)}
_IMG_MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".gif": "image/gif", ".webp": "image/webp"}


class BidSummary(BaseModel):
    buyer: str = ""
    location: str = ""
    project_description: str = ""
    technical_scope: str = ""
    hardware_requirements: str = ""
    software_requirements: str = ""
    deliverables: str = ""
    implementation_timeline: str = ""
    submission_timeline: str = ""
    total_value: str = ""
    emd_value: str = ""
    pbg_value: str = ""
    vendor_qualification: str = ""
    eligibility_restrictions: list[str] = []
    has_restrictive_eligibility: bool = False
    single_vendor: bool = False
    single_vendor_name: str = ""
    single_vendor_favourable: bool = False     # set locally (vs OUR_VENDOR_ALIASES), never by the model
    vendor_lock_clauses: list[str] = []
    # Files we could neither extract nor hand to Sonnet (legacy .doc/.xls/.ppt with no
    # LibreOffice on the box, or unknown formats). Set LOCALLY from extraction — NEVER by the
    # model — so the web app can tell the user "we couldn't read these document(s)" via the
    # same summary surface. We deliberately do NOT install LibreOffice; this is the signal the
    # operator tallies to decide whether legacy support is worth it later.
    unparsed_documents: list[str] = []
    coverage: Literal["full", "partial"] = "full"


_SCHEMA_KEYS = ("buyer, location, project_description, technical_scope, hardware_requirements, "
                "software_requirements, deliverables, implementation_timeline, submission_timeline, "
                "total_value, emd_value, pbg_value, vendor_qualification, eligibility_restrictions, "
                "has_restrictive_eligibility, single_vendor, single_vendor_name, vendor_lock_clauses, "
                "coverage")

PROMPT = (
    "You are analysing a single government/PSU tender to help a technology-services company "
    "decide whether to bid. You are given the tender's already-cleaned text (boilerplate, terms "
    "& conditions, and non-English content have been removed) plus any scanned/image documents "
    "attached directly.\n\n"
    "Extract ONLY decision-relevant TECHNICAL, FINANCIAL, and ELIGIBILITY information. Ignore "
    "generic terms & conditions, legal/governance clauses, signatures, and anything not in English.\n\n"
    f"Return a SINGLE JSON object — no prose, no markdown fences — with EXACTLY these keys: "
    f"{_SCHEMA_KEYS}.\n\n"
    "TYPES (strict — wrong types are rejected): eligibility_restrictions and vendor_lock_clauses "
    "are JSON ARRAYS of strings (use [] if none). has_restrictive_eligibility and single_vendor "
    "are booleans. coverage is \"full\" or \"partial\". EVERY OTHER field — including "
    "vendor_qualification — is a plain STRING (use \"\" if absent); never return an array for them.\n\n"
    "Field rules (use \"\" or [] when absent — NEVER invent):\n"
    "- buyer: procuring organization/department. location: delivery/project site.\n"
    "- vendor_qualification: the bidder pre-qualification / eligibility criteria (turnover, "
    "experience, certifications, mandated facilities) as ONE text block.\n"
    "- technical_scope: the technical work/capabilities required. hardware_requirements / "
    "software_requirements: specific specs/platforms/tools/standards mandated.\n"
    "- total_value / emd_value / pbg_value: contract value, EMD, performance/bid guarantee "
    "(amount or %), with currency.\n"
    "- eligibility_restrictions: broad gates on WHO can bid (turnover, prior experience, "
    "certifications); set has_restrictive_eligibility accordingly.\n"
    "- single_vendor: true ONLY if the WHOLE tender is restricted to one named seller "
    "(single tender / sole-source / nomination / proprietary article); single_vendor_name = that "
    "seller. (Usually handled before you see it — leave false if unsure.)\n"
    "- vendor_lock_clauses: EVERY clause mandating a specific item be procured from a NAMED "
    "company/brand/OEM/authority — e.g. 'data card from XYZ Ltd', 'license from ABC', 'must be "
    "Cisco or equivalent'. Capture item + named vendor. These are go/no-go signals — never omit one.\n"
    "- coverage: 'full' normally; 'partial' only if explicitly told you received a reduced doc set.\n"
)


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _favourable(name: str) -> bool:
    n = (name or "").lower()
    return any(alias in n for alias in config.OUR_VENDOR_ALIASES)


# ── Sonnet payload + call ────────────────────────────────────────────────────────────

def _media_block(path: str) -> dict | None:
    ext = Path(path).suffix.lower()
    try:
        data = base64.standard_b64encode(Path(path).read_bytes()).decode()
    except Exception:
        return None
    if ext == ".pdf":
        return {"type": "document", "source": {"type": "base64",
                "media_type": "application/pdf", "data": data}}
    if ext in _IMG_MEDIA:
        return {"type": "image", "source": {"type": "base64",
                "media_type": _IMG_MEDIA[ext], "data": data}}
    return None


def _build_content(text: str, media: list[str]) -> list[dict]:
    blocks: list[dict] = [{"type": "text", "text": f"TENDER TEXT:\n{text}" if text else
                           "TENDER TEXT: (none — see attached documents)"}]
    for p in media:
        b = _media_block(p)
        if b is not None:
            blocks.append(b)
    return blocks


def _raw_sonnet(content: list[dict], nudge: str = "") -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=config.require_api_key())
    sys_prompt = PROMPT + (f"\n\n{nudge}" if nudge else "")
    resp = client.messages.create(
        model=config.SUMMARY_MODEL, max_tokens=2048,
        system=[{"type": "text", "text": sys_prompt}],
        messages=[{"role": "user", "content": content}])
    return resp.content[0].text


def _parse_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group())
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _call_and_validate(content: list[dict], call_fn) -> BidSummary:
    """Sonnet → JSON → Pydantic, bounded retry feeding the validation error back. Raises
    RuntimeError on exhaustion (caller marks summary_status='failed', does NOT re-queue)."""
    last_err = ""
    for attempt in range(config.SUMMARY_MAX_ATTEMPTS):
        nudge = (f"Your previous output was invalid: {last_err}. Return ONLY a valid JSON "
                 "object with the required keys.") if last_err else ""
        text = call_fn(content, nudge)
        data = _parse_json(text)
        if data is None:
            last_err = "not parseable as a JSON object"
            continue
        try:
            return BidSummary(**data)
        except ValidationError as e:
            last_err = "; ".join(f"{err['loc']}: {err['msg']}" for err in e.errors()[:6])
    raise RuntimeError(f"summary validation failed after {config.SUMMARY_MAX_ATTEMPTS} attempts: {last_err}")


# ── persistence (parent DB overlay; the ONLY thing stored) ────────────────────────────

def _persist(parent: sqlite3.Connection, portal: str, source_pk: str, *, summary: BidSummary | None,
             status: str, model: str, coverage: str = "full") -> None:
    pk = _ADAPTER_PK[portal]
    vals = source_pk.split("|") if len(pk) > 1 else [source_pk]
    where = " AND ".join(f"{c}=?" for c in pk)
    if summary is not None:
        parent.execute(
            f"UPDATE {portal}_bids SET summary_json=?, summary_model=?, summary_generated_at=?, "
            f"docs_summarized=1, summary_status=?, has_restrictive_eligibility=?, summary_coverage=? "
            f"WHERE {where}",
            (summary.model_dump_json(), model, _now(), status,
             1 if (summary.has_restrictive_eligibility or summary.single_vendor
                   or summary.vendor_lock_clauses) else 0, coverage, *vals))
    else:  # failed — no summary stored, flagged for manual review, not re-queued
        parent.execute(
            f"UPDATE {portal}_bids SET summary_status=?, summary_model=?, summary_generated_at=? "
            f"WHERE {where}", (status, model, _now(), *vals))
    parent.commit()


def render_markdown(summary: BidSummary) -> str:
    """Render the stored JSON to markdown for display (the DB keeps JSON; this is a view)."""
    s = summary
    L = [f"## {s.buyer or 'Tender'} — summary", ""]
    if s.unparsed_documents:
        L += ["> **⚠ Unreadable document(s)** — could not be opened locally (legacy/binary "
              "format; not sent to the AI). This summary may be incomplete; manual review needed:",
              *[f"> - {d}" for d in s.unparsed_documents], ""]
    if s.single_vendor:
        fav = "IN OUR FAVOUR ✅" if s.single_vendor_favourable else "restricted to another vendor ❌"
        L += [f"> **Single-vendor tender** — {fav}  (restricted to: {s.single_vendor_name or 'unspecified'})", ""]
    def sec(t, v):
        if v:
            L.append(f"**{t}:** {v}")
    sec("Location", s.location)
    sec("Project", s.project_description)
    sec("Technical scope", s.technical_scope)
    sec("Hardware", s.hardware_requirements)
    sec("Software", s.software_requirements)
    sec("Deliverables", s.deliverables)
    sec("Implementation timeline", s.implementation_timeline)
    sec("Submission timeline", s.submission_timeline)
    sec("Total value", s.total_value)
    sec("EMD", s.emd_value)
    sec("PBG / bid security", s.pbg_value)
    sec("Vendor qualification", s.vendor_qualification)
    if s.vendor_lock_clauses:
        L += ["", "**Vendor-lock (poison pills):**"] + [f"- {c}" for c in s.vendor_lock_clauses]
    if s.eligibility_restrictions:
        L += ["", "**Eligibility restrictions:**"] + [f"- {c}" for c in s.eligibility_restrictions]
    if s.coverage == "partial":
        L += ["", "_⚠ partial coverage — oversized bundle, primary document(s) only; manual review._"]
    return "\n".join(L)


# ── shared fetch + extract ─────────────────────────────────────────────────────────

def _adapter(portal: str):
    return {"hal": __import__("bidplus.adapters.hal", fromlist=["HALAdapter"]).HALAdapter,
            "isro": __import__("bidplus.adapters.isro", fromlist=["ISROAdapter"]).ISROAdapter,
            "gem": __import__("bidplus.adapters.gem", fromlist=["GeMAdapter"]).GeMAdapter}[portal]()


def _fetch_and_extract(portal: str, source_pk: str, fetch: bool):
    """Ensure the bid's docs are staged (fetch only if the dir is empty — never re-fetch
    within the 7-day window) then run Channel-2 extraction. Returns the ExtractionResult."""
    staging = config.bid_staging_dir(portal, source_pk)
    if fetch and (not staging.is_dir() or not any(staging.iterdir())):
        _adapter(portal).fetch_documents(source_pk)
    return extraction.extract_dir(portal, source_pk)


# ── score-4 path: local extraction only, NO Sonnet, NOTHING to Sonnet ────────────────

def _persist_local(parent: sqlite3.Connection, portal: str, source_pk: str,
                   payload: dict, *, restrictive: bool) -> None:
    pk = _ADAPTER_PK[portal]
    vals = source_pk.split("|") if len(pk) > 1 else [source_pk]
    where = " AND ".join(f"{c}=?" for c in pk)
    parent.execute(
        f"UPDATE {portal}_bids SET local_extract_json=?, local_extracted=1, "
        f"has_restrictive_eligibility=? WHERE {where}",
        (json.dumps(payload), 1 if restrictive else 0, *vals))
    parent.commit()


def local_extract_bid(portal: str, source_pk: str, parent: sqlite3.Connection,
                      fetch: bool = True) -> dict:
    """Score-4 path (decision #28 / plan §S6): fetch docs + local regex/heuristic extraction,
    write `local_extract_json` + `local_extracted=1` + the eligibility pre-flag. NO Sonnet call,
    NO summary_json. Pass 2 is deferred to a web-app "Retrieve information" click on the staged
    files. Records any legacy/unreadable docs so the operator sees them in the preview too."""
    ex = _fetch_and_extract(portal, source_pk, fetch)
    unparsed = [d.doc_name for d in ex.unsupported_docs]
    preflag = bool(ex.local_fields.get("eligibility_preflag")) or ex.single_vendor
    payload = dict(ex.local_fields)
    payload.update({
        "single_vendor": ex.single_vendor,
        "single_vendor_name": ex.single_vendor_name,
        "unparsed_documents": unparsed,
    })
    _persist_local(parent, portal, source_pk, payload, restrictive=preflag)
    return {"portal": portal, "bid_id": source_pk, "path": "local_extract",
            "eligibility_preflag": preflag, "unparsed": len(unparsed), "sonnet": False}


# ── score-5 (and on-demand) path: the ONE path to Sonnet ─────────────────────────────

def summarize_bid(portal: str, source_pk: str, parent: sqlite3.Connection,
                  fetch: bool = True, call_fn=None) -> dict:
    """Summarize one bid. Single-vendor → local record (no Sonnet). Nothing readable →
    local 'unreadable docs' record (no Sonnet). Else → Sonnet + Pydantic. Persists only the
    summary to the parent DB. Returns a small status dict."""
    call_fn = call_fn or _raw_sonnet
    ex = _fetch_and_extract(portal, source_pk, fetch)
    unparsed = [d.doc_name for d in ex.unsupported_docs]

    # (1) Single-vendor — decided locally, NO Sonnet call.
    if ex.single_vendor:
        fav = _favourable(ex.single_vendor_name)
        summary = BidSummary(
            buyer="", project_description=(
                f"Single-tender / sole-source bid restricted to "
                f"{ex.single_vendor_name or 'an unspecified vendor'}."),
            single_vendor=True, single_vendor_name=ex.single_vendor_name,
            single_vendor_favourable=fav, has_restrictive_eligibility=True,
            unparsed_documents=unparsed,
            emd_value=ex.local_fields.get("emd_value") or "",
            total_value=ex.local_fields.get("total_value") or "")
        _persist(parent, portal, source_pk, summary=summary, status="ok",
                 model="local:single-vendor")
        return {"portal": portal, "bid_id": source_pk, "path": "single_vendor",
                "favourable": fav, "vendor": ex.single_vendor_name, "sonnet": False}

    # (2) Nothing readable to send (e.g. only legacy/binary docs, no LibreOffice; or no docs).
    # Skip Sonnet — there is nothing to summarize — and record WHY so the web app can tell the
    # user. Marked done so the gate does not re-burn it nightly (terminal until a human acts).
    if not ex.combined_text.strip() and not ex.media_paths:
        why = ("This bid's document(s) are in a legacy/binary format we could not open, so no "
               "summary could be produced." if unparsed else
               "No machine-readable documents were available for this bid.")
        summary = BidSummary(project_description=why, unparsed_documents=unparsed)
        _persist(parent, portal, source_pk, summary=summary, status="ok",
                 model="local:unreadable-docs")
        return {"portal": portal, "bid_id": source_pk, "path": "unreadable_docs",
                "unparsed": len(unparsed), "sonnet": False}

    # (3) Sonnet path — token-budget guard (oversized → primary text only, partial).
    text, media, coverage = ex.combined_text, list(ex.media_paths), "full"
    if len(text) > config.SUMMARY_TOKEN_BUDGET * 4:
        first = ex.text_docs[0].text if ex.text_docs else text[: config.SUMMARY_TOKEN_BUDGET * 4]
        text, media, coverage = first[: config.SUMMARY_TOKEN_BUDGET * 4], [], "partial"

    content = _build_content(text, media)
    try:
        summary = _call_and_validate(content, call_fn)
    except SystemExit:
        raise
    except Exception as e:
        _persist(parent, portal, source_pk, summary=None, status="failed",
                 model=config.SUMMARY_MODEL)
        return {"portal": portal, "bid_id": source_pk, "path": "sonnet",
                "status": "failed", "error": str(e), "sonnet": True}

    summary.unparsed_documents = unparsed
    if coverage == "partial":
        summary.coverage = "partial"
    if summary.single_vendor:  # Sonnet backstop caught one local detection missed
        summary.single_vendor_favourable = _favourable(summary.single_vendor_name)
    _persist(parent, portal, source_pk, summary=summary, status="ok",
             model=config.SUMMARY_MODEL, coverage=summary.coverage)
    return {"portal": portal, "bid_id": source_pk, "path": "sonnet", "status": "ok",
            "coverage": summary.coverage, "restrictive": summary.has_restrictive_eligibility,
            "vendor_lock": len(summary.vendor_lock_clauses),
            "unparsed": len(unparsed), "sonnet": True}

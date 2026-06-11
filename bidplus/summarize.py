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
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, ValidationError, field_validator

import bidplus.config as config
from bidplus import extraction

_ADAPTER_PK = {"hal": ("tender_number", "line_number"), "isro": ("tender_id",), "gem": ("bid_number",)}
_IMG_MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".gif": "image/gif", ".webp": "image/webp"}


# ── critical_flags typed tiers ────────────────────────────────────────────────────────

class T1aFlag(BaseModel):
    tier: Literal["T1a"]
    label: str
    clause: str

class T1bFlag(BaseModel):
    tier: Literal["T1b"]
    label: str
    models: str

class T2Flag(BaseModel):
    tier: Literal["T2"]
    label: str

CriticalFlag = Annotated[Union[T1aFlag, T1bFlag, T2Flag], Field(discriminator="tier")]


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
    critical_flags: list[CriticalFlag] = []
    # Files we could neither extract nor hand to Sonnet (legacy .doc/.xls/.ppt with no
    # LibreOffice on the box, or unknown formats). Set LOCALLY from extraction — NEVER by the
    # model — so the web app can tell the user "we couldn't read these document(s)" via the
    # same summary surface. We deliberately do NOT install LibreOffice; this is the signal the
    # operator tallies to decide whether legacy support is worth it later.
    unparsed_documents: list[str] = []
    coverage: Literal["full", "partial"] = "full"

    @field_validator("critical_flags", mode="before")
    @classmethod
    def _coerce_legacy_flags(cls, v: object) -> object:
        # Old summaries stored critical_flags as list[str]; coerce each string to a T2Flag dict.
        if not isinstance(v, list):
            return v
        return [{"tier": "T2", "label": item} if isinstance(item, str) else item for item in v]


PROMPT = """\
You are analysing a single government/PSU tender to help a technology-services company
decide whether to bid. You are given the tender's already-cleaned text (boilerplate, terms
& conditions, and non-English content have been removed) plus any scanned/image documents
attached directly.

Extract ONLY decision-relevant information. Be terse — summaries, not explanations.
Do NOT recommend. Do NOT judge fit. Surface facts only; a human reviewer decides.

Return a SINGLE JSON object — no prose, no markdown fences — with EXACTLY these keys:
buyer, location, project_description, technical_scope, hardware_requirements,
software_requirements, deliverables, implementation_timeline, submission_timeline,
total_value, emd_value, pbg_value, vendor_qualification, eligibility_restrictions,
has_restrictive_eligibility, single_vendor, single_vendor_name, vendor_lock_clauses,
critical_flags

TYPES:
- critical_flags: JSON ARRAY OF OBJECTS (schema below)
- eligibility_restrictions, vendor_lock_clauses: JSON ARRAYS OF STRINGS
- has_restrictive_eligibility, single_vendor: booleans
- all other fields: plain STRING

BREVITY RULES — apply to every field except critical_flags:
- location: city name only
- project_description: one sentence, max 25 words
- technical_scope: max 4 comma-separated keyword phrases
- hardware_requirements: comma-separated model/platform names only, no descriptions
- software_requirements: comma-separated tool/stack names only, no descriptions
- deliverables: stage name + quantity only (e.g. "Design ×1, Build ×4, Ops Support ×1yr")
- implementation_timeline: max 4 milestones, format "label: date/duration" each
- submission_timeline: deadline datetime only
- total_value / emd_value / pbg_value: amount with currency; "Not stated" if absent
- vendor_qualification: comma-separated criteria titles only, no prose
- eligibility_restrictions: array of short title strings, no body text
- vendor_lock_clauses: array of short title strings, named OEM included, no body text

critical_flags SCHEMA — array of objects, exactly one of three tier formats:

  T1a — OEM Authorization Poison Pill
    A clause requiring the bidder to hold a STATUS granted and controlled by a named OEM
    (system integrator authorization, dealership, partner/channel certification).
    The named OEM decides who qualifies — the bidder cannot self-certify.
    { "tier": "T1a", "label": "<ALL CAPS TITLE>",
      "clause": "<clause verbatim or near-verbatim, named OEM and required status included>" }

  T1b — Mandated Supply Poison Pill
    Named HW or SW the tender explicitly mandates from a specific manufacturer.
    One object per manufacturer. models: model numbers only, comma-separated, no brand prefix.
    { "tier": "T1b", "label": "MANDATED SUPPLY — <MANUFACTURER NAME>",
      "models": "<model1, model2, ...>" }

  T2 — Gate (title only)
    All other bid-relevant gates: process/capability certifications (AS9100D, CEMILAC,
    DO-178C, ISO, CMMI), experience/turnover thresholds, locality/registration requirements,
    staffing, contractual obligations (IPR, NDA, EMD, LD, PBG, bid format).
    Achievable through the bidder's own effort — no named OEM controls access.
    { "tier": "T2", "label": "<ALL CAPS TITLE — include key threshold or value if present>" }

critical_flags rules:
- Capture EVERY clause that could block or constrain a bid. Miss nothing.
- A clause already in eligibility_restrictions or vendor_lock_clauses MUST also appear here.
- Do NOT judge whether the bidder meets any condition. Do NOT recommend. Facts only.
- If none exist, return [].
"""


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
        model=config.SUMMARY_MODEL, max_tokens=config.SUMMARY_MAX_TOKENS,
        system=[{"type": "text", "text": sys_prompt}],
        messages=[{"role": "user", "content": content}])
    if resp.stop_reason == "max_tokens":
        # Truncated JSON would fail to parse with a misleading "not parseable" error and
        # burn every retry on the same wall. Surface the real cause instead.
        raise RuntimeError(
            f"summary output hit max_tokens ({config.SUMMARY_MAX_TOKENS}); raise SUMMARY_MAX_TOKENS")
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
    L: list[str] = []

    # ── alerts ──────────────────────────────────────────────────────────────────────
    if s.unparsed_documents:
        L += ["> ⚠ **Unreadable document(s)** — could not be opened (legacy/binary format; not "
              "sent to the AI). Summary may be incomplete; manual review needed:",
              *[f"> - {d}" for d in s.unparsed_documents], ""]
    if s.single_vendor:
        fav = "IN OUR FAVOUR ✅" if s.single_vendor_favourable else "restricted to another vendor ❌"
        L += [f"> 🔒 **Single-vendor tender** — {fav} "
              f"(restricted to: {s.single_vendor_name or 'unspecified'})", ""]
    if s.coverage == "partial":
        L += ["> ⚠ **Partial coverage** — oversized bundle; primary document(s) only. Manual review advised.", ""]

    # ── overview ────────────────────────────────────────────────────────────────────
    L += ["### Overview", ""]
    if s.location:
        L += [f"**Location:** {s.location}", ""]
    if s.project_description:
        L += [f"**Project:** {s.project_description}", ""]

    # ── scope ───────────────────────────────────────────────────────────────────────
    scope_items = [
        ("Technical Scope", s.technical_scope),
        ("Hardware Requirements", s.hardware_requirements),
        ("Software Requirements", s.software_requirements),
        ("Deliverables", s.deliverables),
    ]
    if any(v for _, v in scope_items):
        L += ["### Scope & Requirements", ""]
        for label, val in scope_items:
            if val:
                L += [f"**{label}**", "", val, ""]

    # ── timeline ────────────────────────────────────────────────────────────────────
    timeline_items = [
        ("Implementation Timeline", s.implementation_timeline),
        ("Submission Deadline", s.submission_timeline),
    ]
    if any(v for _, v in timeline_items):
        L += ["### Timeline", ""]
        for label, val in timeline_items:
            if val:
                L += [f"**{label}:** {val}", ""]

    # ── financials ──────────────────────────────────────────────────────────────────
    fin_items = [
        ("Contract Value", s.total_value),
        ("EMD / Bid Security", s.emd_value),
        ("Performance Bank Guarantee", s.pbg_value),
    ]
    if any(v for _, v in fin_items):
        L += ["### Financials", ""]
        for label, val in fin_items:
            if val:
                L += [f"**{label}:** {val}", ""]

    # ── eligibility ─────────────────────────────────────────────────────────────────
    if s.vendor_qualification or s.eligibility_restrictions:
        L += ["### Eligibility & Qualification", ""]
        if s.vendor_qualification:
            L += [s.vendor_qualification, ""]
        if s.eligibility_restrictions:
            L += [f"- {r}" for r in s.eligibility_restrictions]
            L += [""]

    # ── vendor lock ─────────────────────────────────────────────────────────────────
    if s.vendor_lock_clauses:
        L += ["### Vendor-Lock Clauses", ""]
        L += [f"- {c}" for c in s.vendor_lock_clauses]

    return "\n".join(L)


# ── single tender detection ───────────────────────────────────────────────────────

_ST_APPLICABLE_RE = re.compile(
    r"single[\s\-–]*tender[\s\-–]*applicable\s*[:\-]?\s*(yes|हाँ|हां|ha\b)",
    re.IGNORECASE,
)
_ST_ORG_RE = re.compile(
    r"(?:list\s+of\s+seller\s+org(?:anization)?[^\n]{0,40}?participation"
    r"|seller\s+org(?:anization)?[^\n]{0,40}?participation)"
    r"\s*[:\-]?\s*(.{3,150}?)(?:\n|$)",
    re.IGNORECASE,
)
_TECLEVER_RE = re.compile(r"teclever", re.IGNORECASE)
_MASKED_RE   = re.compile(r"\*{2,}|x{5,}|\?{3,}", re.IGNORECASE)


def _detect_single_tender(text: str) -> tuple[bool, str | None]:
    """Scan extracted text for 'Single Tender Applicable: Yes'.
    Returns (is_single_tender, org_name_or_None)."""
    if not _ST_APPLICABLE_RE.search(text):
        return False, None
    m = _ST_ORG_RE.search(text)
    org = m.group(1).strip() if m else None
    return True, org


def _st_class(org: str | None) -> str:
    """Classify org: 'teclever' | 'masked' | 'other'."""
    if not org or _MASKED_RE.search(org):
        return "masked"
    if _TECLEVER_RE.search(org):
        return "teclever"
    return "other"


def _apply_single_tender_db(parent: sqlite3.Connection, portal: str,
                             source_pk: str, org: str | None, cls: str) -> None:
    """Persist single tender detection results and apply scoring/rejection overrides.

    pass1_score / auto_rejected are tool-mirrored columns — the merge copies them
    from the tool DB whenever values differ, so the override MUST be written to the
    tool DB as well or the next nightly merge silently reverts it."""
    pk = _ADAPTER_PK[portal]
    vals = source_pk.split("|") if len(pk) > 1 else [source_pk]
    where = " AND ".join(f"{c}=?" for c in pk)
    if cls == "other":
        parent.execute(
            f"UPDATE {portal}_bids SET is_single_tender=1, single_tender_org=?, "
            f"auto_rejected=1, user_state='rejected', disposed_at=? WHERE {where}",
            (org, _now(), *vals),
        )
        tool_sql = "SET auto_rejected=1"
    else:
        # Teclever or masked → score 5 so it runs through Sonnet automatically
        parent.execute(
            f"UPDATE {portal}_bids SET is_single_tender=1, single_tender_org=?, "
            f"pass1_score=5 WHERE {where}",
            (org or "***", *vals),
        )
        tool_sql = "SET pass1_score=5"
    parent.commit()

    adapter = _adapter(portal)
    tool_table = adapter._SCORING["table"]
    try:
        tool = sqlite3.connect(adapter.tool_db_path())
        try:
            tool.execute(f"UPDATE {tool_table} {tool_sql} WHERE {where}", vals)
            tool.commit()
        finally:
            tool.close()
    except Exception as e:
        print(f"[single-tender] WARNING: tool DB update failed for {portal} "
              f"{source_pk}: {e} — parent override may revert on next merge")


def _read_staging_text(portal: str, source_pk: str) -> str:
    """Read all .txt extraction files from the staging dir (raw, for detection)."""
    staging = config.bid_staging_dir(portal, source_pk)
    if not staging.is_dir():
        return ""
    parts: list[str] = []
    for p in sorted(staging.iterdir()):
        if p.is_file() and p.suffix == ".txt":
            try:
                parts.append(p.read_text(errors="replace"))
            except Exception:
                pass
    return "\n".join(parts)


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
    """Score-4 path: fetch docs + local extraction. Promotes to Sonnet if single tender
    Teclever/masked is detected. Rejects immediately if single tender non-Teclever."""
    ex = _fetch_and_extract(portal, source_pk, fetch)
    # Single tender detection: regex on raw .txt first, extraction detector as fallback
    raw = _read_staging_text(portal, source_pk)
    is_st, st_org = _detect_single_tender(raw)
    if not is_st and ex.single_vendor:
        is_st, st_org = True, ex.single_vendor_name
    if is_st:
        cls = _st_class(st_org)
        _apply_single_tender_db(parent, portal, source_pk, st_org, cls)
        if cls == "other":
            return {"portal": portal, "bid_id": source_pk, "path": "single_tender_rejected",
                    "org": st_org, "sonnet": False, "single_tender": True}
        # Teclever or masked: score upgraded to 5, run Sonnet immediately
        return summarize_bid(portal, source_pk, parent, fetch=False)
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
    """Summarize one bid. Single-tender/single-vendor detection runs first (regex on
    raw .txt, extraction detector as fallback — ONE set of DB consequences for both):
    non-Teclever → auto-reject + local stub summary, no Sonnet; Teclever/masked →
    score 5 + flags set, then the FULL Sonnet summary runs (operator decision)."""
    call_fn = call_fn or _raw_sonnet
    ex = _fetch_and_extract(portal, source_pk, fetch)
    raw = _read_staging_text(portal, source_pk)
    is_st, st_org = _detect_single_tender(raw)
    if not is_st and ex.single_vendor:
        is_st, st_org = True, ex.single_vendor_name
    unparsed = [d.doc_name for d in ex.unsupported_docs]

    if is_st:
        cls = _st_class(st_org)
        _apply_single_tender_db(parent, portal, source_pk, st_org, cls)
        if cls == "other":
            # Restricted to another vendor — outcome decided, no Sonnet. Store a local
            # stub summary so the detail page still shows why.
            summary = BidSummary(
                buyer="", project_description=(
                    f"Single-tender / sole-source bid restricted to "
                    f"{st_org or 'an unspecified vendor'}."),
                single_vendor=True, single_vendor_name=st_org or "",
                single_vendor_favourable=False, has_restrictive_eligibility=True,
                unparsed_documents=unparsed,
                emd_value=ex.local_fields.get("emd_value") or "",
                total_value=ex.local_fields.get("total_value") or "")
            _persist(parent, portal, source_pk, summary=summary, status="ok",
                     model="local:single-vendor")
            return {"portal": portal, "bid_id": source_pk, "path": "single_tender_rejected",
                    "org": st_org, "sonnet": False, "single_tender": True}
        # Teclever or masked: flags + score 5 set; fall through to the full Sonnet summary.

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
    summary.coverage = coverage   # Python controls this — never let Sonnet self-assign 'partial'
    if summary.single_vendor:  # Sonnet backstop caught one local detection missed
        summary.single_vendor_favourable = _favourable(summary.single_vendor_name)
        if not is_st:  # local detectors missed it — apply the same DB consequences
            _apply_single_tender_db(parent, portal, source_pk,
                                    summary.single_vendor_name,
                                    _st_class(summary.single_vendor_name))
    _persist(parent, portal, source_pk, summary=summary, status="ok",
             model=config.SUMMARY_MODEL, coverage=summary.coverage)
    return {"portal": portal, "bid_id": source_pk, "path": "sonnet", "status": "ok",
            "coverage": summary.coverage, "restrictive": summary.has_restrictive_eligibility,
            "vendor_lock": len(summary.vendor_lock_clauses),
            "unparsed": len(unparsed), "sonnet": True}

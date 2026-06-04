"""Pass 2 scorer — PDF processing and Sonnet deep-scoring.

score_tender_pass2(tender, capability_ref, context) is the main entry point.
It receives a live Playwright BrowserContext (created once in hal_tool.py for
the whole pass-2 run) and opens/closes its own pages within that context.

Pass 2 per-tender flow:
  1. Open a fresh page in the shared context.
  2. Navigate to the HAL portal home and open the Tender Free View.
  3. Fill in the tender number and click Search (filtered 1-result page).
  4. Click the row's Actions gear → 'Show tender documents'.
  5. Collect all DownloadController URLs from the resulting page.
  6. Download each PDF via context.request.get() (shared session cookies).
  7. Filter boilerplate docs by filename, extract and clean text.
  8. Call Sonnet with cleaned text (or raw base64 for low-text PDFs).
  9. Parse response, save PDFs to downloads/{recommendation}/{date}/{tender}/.
"""

import base64
import datetime
import io
import re
import sys
import time
from pathlib import Path

import anthropic
import pdfplumber

from config import (
    ANTHROPIC_API_KEY,
    DOWNLOADS_DIR,
    PASS2_LOW_TEXT_CHARS,
    PASS2_MODEL,
    REC_TO_FOLDER,
    SCRAPE_DELAY_SECONDS,
)


# ═══════════════════════════════════════════════════════════════════════════════
# PART A — PDF PROCESSING
# ═══════════════════════════════════════════════════════════════════════════════

# Filenames matching any of these substrings are boilerplate — skip them.
_BOILERPLATE_DOC_SUBSTRINGS: tuple[str, ...] = (
    "as9100d",
    "checklist",
    "debar letter",
    "pbg format",
    "omnibus ip",
    "standalone ip",
    "annexure ii a",
    "annexure ii b",
    "integrity pact",
    "vendor registration",
    "pre-qualification",
)


def is_boilerplate_document(filename: str) -> bool:
    """Return True if the filename matches a known boilerplate document."""
    name_lower = (filename or "").lower()
    return any(s in name_lower for s in _BOILERPLATE_DOC_SUBSTRINGS)


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from all pages of a PDF using pdfplumber."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
        return "\n".join(pages)
    except Exception:
        return ""


_CID_RE = re.compile(r"\(cid:\d+\)")

_BOILERPLATE_SECTION_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"general\s+terms\s+and\s+conditions",
        r"\bterms\s+and\s+conditions\b",
        r"\bintegrity\s+pact\b",
        r"\bvendor\s+declaration\b",
        r"\barbitration\s+clause\b",
        r"\bforce\s+majeure\b",
        r"\bliquidated\s+damages\b",
        r"performance\s+(?:bank\s+)?guarantee\b",
        r"\bpenalty\s+clause\b",
        r"\bwarranty\s+clause\b",
        r"\bindemnification\b",
        r"\bgoverning\s+law\b",
        r"\bdispute\s+resolution\b",
    )
)

_BOILERPLATE_INLINE_PHRASES: tuple[str, ...] = (
    "authorised signatory",
    "authorized signatory",
    "signature of vendor",
    "signature of tenderer",
    "this is a computer generated",
    "computer-generated document",
    "duly authorized representative",
    "for and on behalf of",
    "place and date",
    "witness :",
    "witness:",
    "seal of the",
    "stamp and signature",
)

_MAJOR_SECTION_RE = re.compile(
    r"^\s*(?:\d+[\.\)]\s|\([a-z]\)\s|[A-Z]\.\s|SECTION\s+\d+|"
    r"Annexure\s+[A-Z0-9]|Appendix\s+[A-Z0-9]|Enclosure\s+\d+)",
    re.IGNORECASE,
)


def _remove_boilerplate_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    in_boilerplate_section = False

    for line in lines:
        stripped = line.strip()
        lower    = stripped.lower()

        is_bp_header  = any(p.search(stripped) for p in _BOILERPLATE_SECTION_PATTERNS)
        is_major_hdr  = bool(_MAJOR_SECTION_RE.match(stripped)) or (
            stripped.isupper() and 3 < len(stripped) <= 60 and len(stripped.split()) <= 8
        )

        if is_bp_header:
            in_boilerplate_section = True
            continue

        if in_boilerplate_section:
            if is_major_hdr:
                in_boilerplate_section = False
                result.append(line)
            continue

        if any(phrase in lower for phrase in _BOILERPLATE_INLINE_PHRASES):
            continue

        result.append(line)

    return result


def extract_and_clean(pdf_bytes: bytes) -> str:
    """Extract text from a PDF and apply full cleaning pipeline."""
    raw = extract_pdf_text(pdf_bytes)
    if not raw:
        return ""

    text  = _CID_RE.sub("", raw)
    lines = _remove_boilerplate_lines(text.splitlines())

    cleaned: list[str] = []
    blank_run = 0
    for line in lines:
        if line.strip() == "":
            blank_run += 1
            if blank_run <= 2:
                cleaned.append(line)
        else:
            blank_run = 0
            cleaned.append(line)

    return "\n".join(cleaned).strip()


# ── Financial value extraction ─────────────────────────────────────────────────

_AMOUNT_RE = re.compile(
    r"(?:Rs\.?\s*|INR\s*|₹\s*)(\d[\d,\.]*(?:\s*(?:Lakhs?|Lacs?|Crores?|Cr|L))?(?:/-)?)"
    r"|(\d[\d,\.]*\s*(?:Lakhs?|Lacs?|Crores?|Cr|L)(?:/-)?)",
    re.IGNORECASE,
)
_EMD_KEYWORD_RE = re.compile(
    r"(?:EMD|Earnest\s+Money(?:\s+Deposit)?|Security\s+Deposit)",
    re.IGNORECASE,
)
_CONTRACT_VALUE_KEYWORD_RE = re.compile(
    r"(?:Estimated\s+(?:Cost|Value|Project\s+Cost)|"
    r"Total\s+(?:Value|Project\s+Cost|Contract\s+Value)|"
    r"Contract\s+Value|Project\s+Value|"
    r"Approximate\s+(?:Cost|Value))",
    re.IGNORECASE,
)


def _find_amount_near(text: str, keyword_re: re.Pattern, window: int = 350) -> str | None:
    m = keyword_re.search(text)
    if not m:
        return None
    start   = max(0, m.start() - window // 2)
    end     = min(len(text), m.end() + window)
    snippet = text[start:end]
    am = _AMOUNT_RE.search(snippet)
    if am:
        return (am.group(1) or am.group(2) or "").strip()
    return None


def extract_emd_amount(text: str) -> str | None:
    return _find_amount_near(text, _EMD_KEYWORD_RE)


def extract_contract_value(text: str) -> str | None:
    return _find_amount_near(text, _CONTRACT_VALUE_KEYWORD_RE)


# ── PDF save ───────────────────────────────────────────────────────────────────

def _save_pdf(pdf_bytes: bytes, tender_number: str, filename: str, recommendation: str) -> Path:
    """Save a PDF to downloads/{recommendation}/{YYYY-MM-DD}/{sanitized_tn}/{filename}."""
    folder_name  = REC_TO_FOLDER.get(recommendation.upper(), "Assess_Further")
    sanitized_tn = tender_number.replace("/", "_")
    today        = datetime.date.today().isoformat()
    dest_dir     = DOWNLOADS_DIR / folder_name / today / sanitized_tn
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest = dest_dir / filename
    counter = 1
    while dest.exists():
        dest = dest_dir / f"{Path(filename).stem}_{counter}{Path(filename).suffix}"
        counter += 1

    dest.write_bytes(pdf_bytes)
    return dest


# ═══════════════════════════════════════════════════════════════════════════════
# PART B — PASS 2 SCORING
# ═══════════════════════════════════════════════════════════════════════════════

from modules.db import set_pass2_attempted


# ── Anthropic client (lazy) ───────────────────────────────────────────────────

_p2_client: anthropic.Anthropic | None = None


def _get_p2_client() -> anthropic.Anthropic:
    global _p2_client
    if _p2_client is None:
        _p2_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _p2_client


# ── Prompt builders ───────────────────────────────────────────────────────────

def _build_pass2_system(capability_ref: str) -> list[dict]:
    return [{"type": "text", "text": capability_ref, "cache_control": {"type": "ephemeral"}}]


def _build_pass2_prompt(tender: dict, combined_text: str) -> str:
    lines = [
        "Analyse the following tender for capability alignment.",
        "",
        "TENDER DETAILS:",
        f"  Tender Number : {tender.get('tender_number', '?')}",
        f"  Line Number   : {tender.get('line_number', '?')}",
        f"  Description   : {tender.get('tender_description', '?')}",
        f"  Buyer         : {tender.get('buyer', '?')}",
        f"  Region        : {tender.get('tender_region', '?')}",
        f"  Closing Date  : {tender.get('closing_date', '?')}",
        f"  Estimated Cost: {tender.get('estimated_cost', '?')}",
        f"  EMD (listing) : {tender.get('emd_listing', '?')}",
        "",
        "TENDER DOCUMENTS (extracted and cleaned text):",
        "",
        combined_text or "(no text extracted — document may be image-only or encrypted)",
        "",
        "Provide your analysis in the exact format specified in the capability reference.",
    ]
    return "\n".join(lines)


# ── API call ──────────────────────────────────────────────────────────────────

def _call_pass2_api(
    tender: dict,
    combined_text: str,
    capability_ref: str,
    pdf_bytes_list: list[bytes],
) -> str | None:
    """Call Sonnet for one tender. Sends extracted text, or raw PDFs as base64
    if extracted text is below PASS2_LOW_TEXT_CHARS (handles image-only PDFs)."""
    client  = _get_p2_client()
    system  = _build_pass2_system(capability_ref)
    prompt  = _build_pass2_prompt(tender, combined_text)
    use_b64 = len(combined_text) < PASS2_LOW_TEXT_CHARS and bool(pdf_bytes_list)
    tn      = tender.get("tender_number", "?")

    if use_b64:
        content: list[dict] = []
        for raw_bytes in pdf_bytes_list:
            content.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.b64encode(raw_bytes).decode(),
                },
            })
        content.append({"type": "text", "text": prompt})
    else:
        content = prompt  # type: ignore[assignment]

    try:
        resp = client.messages.create(
            model=PASS2_MODEL,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": content}],
        )
        return resp.content[0].text
    except anthropic.OverloadedError:
        print(f"  [pass2] API overloaded — skipping {tn}", flush=True)
        return None
    except anthropic.RateLimitError:
        print(f"  [pass2] Rate limit — waiting 30 s then retrying {tn}", flush=True)
        time.sleep(30)
        try:
            resp = client.messages.create(
                model=PASS2_MODEL,
                max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": content}],
            )
            return resp.content[0].text
        except Exception:
            return None
    except anthropic.PermissionDeniedError as e:
        print(f"\n[pass2] Billing limit reached — cannot continue: {e}", file=sys.stderr)
        sys.exit(1)
    except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
        print(f"  [pass2] Connection error for {tn}: {e}", flush=True)
        return None


# ── Response parser ───────────────────────────────────────────────────────────

def parse_score_response(text: str) -> dict:
    """Parse the structured Sonnet response into a pass2 result dict."""
    def _get(label: str) -> str:
        m = re.search(
            rf'(?:^|\n){re.escape(label)}\s*:[ \t]*(.*?)(?=\n[A-Z][A-Z ]+\s*:|\Z)',
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if not m:
            return ""
        val = re.sub(r"\s+", " ", m.group(1)).strip()
        # Strip markdown code fences the model sometimes emits
        val = val.strip("`").strip()
        return val

    raw_score = _get("SCORE")
    try:
        score = int(re.search(r"\d", raw_score).group())
    except (AttributeError, ValueError):
        score = 0

    # Normalise recommendation to one of the four standard labels
    raw_rec = _get("RECOMMENDATION").upper()
    rec = ""
    for standard in ("PURSUE WITH RAMP-UP", "PURSUE", "ASSESS FURTHER", "DECLINE"):
        if standard in raw_rec:
            rec = standard
            break

    return {
        "pass2_score":          score,
        "pass2_confidence":     _get("CONFIDENCE"),
        "pass2_domain":         _get("DOMAIN MATCH"),
        "pass2_gaps":           _get("GAPS"),
        "pass2_rationale":      _get("RATIONALE"),
        "pass2_recommendation": rec,
    }


def _derive_recommendation(score: int) -> str:
    if score >= 4:
        return "PURSUE"
    if score == 3:
        return "PURSUE WITH RAMP-UP"
    if score == 2:
        return "ASSESS FURTHER"
    return "DECLINE"


# ── Main orchestrator ─────────────────────────────────────────────────────────

def score_tender_pass2(
    tender: dict,
    capability_ref: str,
    context,
    search_page,
    search_url: str,
) -> dict | None:
    """Run the complete Pass 2 flow for one tender.

    Reuses the shared `search_page` (the portal's UiRenderer.jsp search form)
    rather than re-navigating through the Mobility SPA for every tender.  For
    each tender the search page is reloaded to its empty-form state via
    `search_url`, the tender number is filled in, and Search is clicked.

    Only popup pages opened during this call (VendorDocumentsController, etc.)
    are closed on exit; `search_page` is left open for the next tender.

    Returns a dict with pass2_* columns + emd_amount + contract_value, or None
    if the flow could not complete. pass2_attempted is set first so a crash
    never causes an infinite retry.
    """
    from modules.session import fill_tender_number, find_results_scope
    from modules.fetcher import open_tender_documents, download_document, find_tender_row

    tn = tender.get("tender_number", "?")
    ln = str(tender.get("line_number", "?"))

    # Mark attempted before any I/O — prevents endless retry on failure
    set_pass2_attempted(tn, ln)

    # Track pages already open so we only close the ones we add
    pages_before_ids = {id(pg) for pg in context.pages}

    try:
        # ── Reset search page to the empty form state ───────────────────────────
        try:
            search_page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(SCRAPE_DELAY_SECONDS)
        except Exception as e:
            print(f"  [pass2] Could not reset search page for {tn}: {e}", flush=True)
            return None

        # Fill tender number before find_results_scope clicks Search
        if not fill_tender_number(search_page, tn):
            print(f"  [pass2] Could not fill tender number field for {tn}", flush=True)

        # find_results_scope clicks Search internally, then waits for #myTable
        results_page = find_results_scope(context, timeout_ms=60_000)
        if results_page is None:
            print(f"  [pass2] Results page not found for {tn} — skipping", flush=True)
            return None

        # ── Locate this tender's row (filter may not have narrowed results) ──────
        row_idx = find_tender_row(results_page, tn)
        if row_idx is None:
            print(f"  [pass2] {tn} not found in results table — skipping", flush=True)
            return None
        if row_idx != 0:
            print(f"  [pass2] Found {tn} at row {row_idx}", flush=True)

        # ── Collect document download URLs via the Actions gear ────────────────
        doc_urls = open_tender_documents(context, results_page, row_idx=row_idx)

        if not doc_urls:
            print(f"  [pass2] No document URLs found for {tn} (may be GEM-routed)", flush=True)
            # GeM-routed tenders legitimately have no attachments — valid result
            # We still call the API with empty documents so we get a score
        else:
            print(f"  [pass2] Found {len(doc_urls)} document URL(s) for {tn}", flush=True)

        # ── Download, filter, and extract text from each PDF ───────────────────
        seen_names: set[str]                = set()
        downloads:  list[tuple[bytes, str]] = []   # (raw_bytes, filename)
        texts:      list[str]               = []

        for i, url in enumerate(sorted(doc_urls), 1):
            result = download_document(context, url, i, seen_names)
            if result is None:
                continue
            raw_bytes, fname = result

            if is_boilerplate_document(fname):
                continue

            downloads.append((raw_bytes, fname))
            cleaned = extract_and_clean(raw_bytes)
            if cleaned:
                texts.append(f"=== {fname} ===\n{cleaned}")

        # ── Combine text and extract financial values ───────────────────────────
        combined_text  = "\n\n".join(texts)
        emd_amount     = extract_emd_amount(combined_text)
        contract_value = extract_contract_value(combined_text)

        # ── Sonnet API call ────────────────────────────────────────────────────
        pdf_bytes_list = [b for b, _ in downloads]
        response_text  = _call_pass2_api(tender, combined_text, capability_ref, pdf_bytes_list)
        if not response_text:
            return None

        # ── Parse response ─────────────────────────────────────────────────────
        result = parse_score_response(response_text)

        if not result.get("pass2_recommendation"):
            result["pass2_recommendation"] = _derive_recommendation(result.get("pass2_score", 0))

        if emd_amount:
            result["emd_amount"] = emd_amount
        if contract_value:
            result["contract_value"] = contract_value

        # ── Save PDFs ──────────────────────────────────────────────────────────
        recommendation = result.get("pass2_recommendation", "ASSESS FURTHER")
        for raw_bytes, fname in downloads:
            try:
                _save_pdf(raw_bytes, tn, fname, recommendation)
            except Exception as e:
                print(f"  [pass2]   PDF save failed for {fname}: {e}", flush=True)

        print(
            f"  [pass2] {tn} → score={result.get('pass2_score')} rec={recommendation}",
            flush=True,
        )
        return result

    except Exception as exc:
        print(f"  [pass2] Unexpected error for {tn}: {exc}", flush=True)
        return None

    finally:
        # Close popup pages opened during this call (e.g. VendorDocumentsController)
        # but leave search_page open — it is shared across all tenders.
        for pg in list(context.pages):
            if id(pg) not in pages_before_ids and pg is not search_page:
                try:
                    pg.close()
                except Exception:
                    pass

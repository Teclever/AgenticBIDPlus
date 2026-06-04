import re, sys, base64, datetime, io
from pathlib import Path
import requests, anthropic, pdfplumber
from modules.csrf_handler import get_session

_MIN_TEXT_CHARS = 500

_BOILERPLATE_PHRASES = [
    "Preference to Make in India",
    "Udyam Registration",
    "Labour Codes",
    "Thank You",
    "land border",
]

_CID_RE         = re.compile(r'\(cid:\d+\)')
_CLAUSE_START   = re.compile(r'^\d+\.\s')          # numbered clause: "3. Preference..."
_PAGE_MARKER    = re.compile(r'^\d+ / \d+$')        # page counter: "3 / 9"
_SINGLE_TENDER_VENDOR_RE = re.compile(
    r'(?:List of Seller )?[Oo]rganization for participation\s+(.+?)(?:\n|$)'
)


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages).strip()


def _remove_boilerplate_lines(lines: list[str]) -> list[str]:
    """
    Remove lines containing boilerplate phrases, extended to cover the full
    enclosing numbered clause (scan back to clause start, forward to next
    non-boilerplate clause or a page marker).
    """
    n = len(lines)

    def _contains_bp(line: str) -> bool:
        ll = line.lower()
        return any(p.lower() in ll for p in _BOILERPLATE_PHRASES)

    # Step 1: mark seed lines
    seed = [_contains_bp(l) for l in lines]

    # Step 2: expand each seed backwards to its clause-start line
    to_remove: set[int] = set()
    for i in range(n):
        if not seed[i]:
            continue
        # Scan back up to 50 lines to find the numbered clause this belongs to
        start = i
        for j in range(i - 1, max(i - 50, -1), -1):
            if _CLAUSE_START.match(lines[j].strip()):
                start = j
                break
            if _PAGE_MARKER.match(lines[j].strip()):
                break   # Don't cross page boundaries when scanning back
        # Scan forward to end of clause (stop at next non-boilerplate clause)
        end = i
        for j in range(i + 1, min(i + 80, n)):
            if _CLAUSE_START.match(lines[j].strip()) and not seed[j]:
                break   # Next clean numbered clause — stop here
            if _PAGE_MARKER.match(lines[j].strip()):
                end = j   # Include page marker in removal
                break
            end = j
        for k in range(start, end + 1):
            to_remove.add(k)

    return [l for i, l in enumerate(lines) if i not in to_remove]


def extract_and_clean(pdf_bytes: bytes) -> str:
    """
    Extract PDF text, strip CID encoding artifacts and GeM boilerplate clauses,
    detect single-tender bids.

    Returns cleaned text, prefixed with [SINGLE TENDER — restricted to: <vendor>]
    when applicable. Word count is always lower than raw extraction.
    """
    raw = _extract_pdf_text(pdf_bytes)

    # Remove CID font encoding artifacts (undecoded Devanagari glyphs)
    text = _CID_RE.sub('', raw)

    # Detect single tender before removing any content
    vendor = None
    if re.search(r'single tender applicable\s+yes', text, re.IGNORECASE):
        m = _SINGLE_TENDER_VENDOR_RE.search(text)
        vendor = m.group(1).strip() if m else "unknown vendor"

    lines = text.split('\n')
    lines = _remove_boilerplate_lines(lines)
    text = '\n'.join(lines)

    # Normalise whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    if vendor:
        text = f"[SINGLE TENDER — restricted to: {vendor}]\n\n{text}"

    return text

BASE_URL = "https://bidplus.gem.gov.in"

_REC_TO_FOLDER = {
    "PURSUE":             "Pursue",
    "PURSUE WITH RAMP-UP": "Pursue",
    "ASSESS FURTHER":     "Assess Further",
    "DECLINE":            "Decline",
}

# ── Spec document fetching ────────────────────────────────────────────────────

_MAX_SPEC_DOCS  = 3     # max supplementary docs to download per bid
_MAX_SPEC_CHARS = 2000  # chars kept per spec doc (token budget control)

# URLs to skip entirely — not spec content
_SKIP_URL_RE = re.compile(
    r'downloadOmppdfile|\.xlsx|\.csv|gtc/pdfByDate|downloadMseMiiDoc|'
    r'admin\.gem\.gov\.in|bidsla/|BoqDocument|BoqLineItems|meet\.google',
    re.I
)

# Priority order: lower number = fetch first
# Matches are tested against the full URL
_SPEC_URL_RANKS = [
    (1, re.compile(r'SpecificationDocument', re.I)),
    (2, re.compile(r'/(?:SOW|scope[_\-]?of[_\-]?work|tech[_\-]?spec|rfq|specification)[^/]*\.pdf', re.I)),
    (3, re.compile(r'bidplus\.gem\.gov\.in/bidding/bid/documentdownload/', re.I)),
    (4, re.compile(r'bidplus\.gem\.gov\.in/resources/upload_nas/.*?/biddoc/', re.I)),
    (5, re.compile(r'fulfilment\.gem\.gov\.in/contract/slafds.*\.pdf', re.I)),
]


def _rank_spec_url(url: str) -> int | None:
    """Return priority rank (1 = highest) or None if URL should be skipped."""
    if _SKIP_URL_RE.search(url):
        return None
    # Must end in .pdf or be a fulfilment slafds URL (path param ends in .pdf)
    lower = url.lower()
    if not (lower.endswith('.pdf') or ('slafds' in lower and '.pdf' in lower)):
        return None
    for rank, pat in _SPEC_URL_RANKS:
        if pat.search(url):
            return rank
    return None


def extract_spec_links(pdf_bytes: bytes) -> list[str]:
    """
    Extract hyperlink annotation URLs from a PDF, filter to spec-relevant ones,
    and return up to _MAX_SPEC_DOCS URLs ordered by priority rank.
    Deduplicates by URL.
    """
    seen: set[str] = set()
    ranked: list[tuple[int, str]] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            for annot in (page.annots or []):
                url = (annot.get('uri') or annot.get('URI', '')).strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                rank = _rank_spec_url(url)
                if rank is not None:
                    ranked.append((rank, url))

    ranked.sort(key=lambda x: x[0])
    return [url for _, url in ranked[:_MAX_SPEC_DOCS]]


def _download_spec_pdf(url: str, session) -> bytes | None:
    """
    Download a spec PDF.
    - bidplus.gem.gov.in → use CSRF session (auth required)
    - Other GeM domains (mkp, fulfilment) → try plain GET first (often public)
    Returns None if download fails or response is not a PDF.
    """
    try:
        if 'bidplus.gem.gov.in' in url:
            resp = session.get(url, timeout=20)
        else:
            resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        if not resp.content.startswith(b'%PDF'):
            return None
        return resp.content
    except Exception:
        return None


def _save_spec_pdf(pdf_bytes: bytes, bid_number: str, index: int):
    """Save supplementary spec PDF to downloads/specs/<date>/."""
    from config import DOWNLOADS_DIR
    folder = Path(DOWNLOADS_DIR) / "specs" / datetime.date.today().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    filename = bid_number.replace("/", "_") + f"_spec_{index}.pdf"
    (folder / filename).write_bytes(pdf_bytes)


def _fetch_spec_texts(pdf_bytes: bytes, bid_number: str) -> list[str]:
    """
    Extract spec annotation links from the main PDF, download each,
    and return cleaned text chunks (capped at _MAX_SPEC_CHARS per doc).
    """
    links = extract_spec_links(pdf_bytes)
    if not links:
        return []

    texts: list[str] = []
    session, _ = get_session()

    for i, url in enumerate(links, 1):
        spec_bytes = _download_spec_pdf(url, session)
        if not spec_bytes:
            print(f"  [spec] doc {i}: download failed or not PDF — {url.split('/')[-1][:60]}")
            continue
        try:
            spec_text = extract_and_clean(spec_bytes)
        except Exception as e:
            print(f"  [spec] doc {i}: text extraction failed — {e}")
            continue
        if len(spec_text) < 100:
            continue
        texts.append(spec_text[:_MAX_SPEC_CHARS])
        _save_spec_pdf(spec_bytes, bid_number, i)
        print(f"  [spec] doc {i}: {len(spec_text)} chars — {url.split('/')[-1][:60]}")

    return texts


def download_pdf(internal_id: str) -> bytes:
    """Download bid document PDF and return raw bytes."""
    session, _ = get_session()
    url = f"{BASE_URL}/showbidDocument/{internal_id}"
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.content


def _save_pdf(pdf_bytes: bytes, bid_number: str, recommendation: str):
    """Save PDF to downloads/<category>/<run_date>/<bid_number>.pdf"""
    from config import DOWNLOADS_DIR
    category = _REC_TO_FOLDER.get((recommendation or "").strip().upper(), "Decline")
    run_date = datetime.date.today().isoformat()
    folder = Path(DOWNLOADS_DIR) / category / run_date
    folder.mkdir(parents=True, exist_ok=True)
    filename = bid_number.replace("/", "_") + ".pdf"
    (folder / filename).write_bytes(pdf_bytes)
    print(f"  [pdf] saved → downloads/{category}/{run_date}/{filename}")


_SINGLE_TENDER_PREFIX_RE = re.compile(
    r'^\[SINGLE TENDER — restricted to: (.+?)\]', re.IGNORECASE
)

_EMD_AMT_RE = re.compile(r'EMD Amount\s*(?:\(In INR\))?\s*(\d[\d,\.]*)', re.IGNORECASE)
_EMD_REQ_RE = re.compile(r'EMD Detail.*?Required\s+(Yes|No)', re.IGNORECASE | re.DOTALL)


def extract_emd_amount(text: str) -> str | None:
    """
    Returns "Exempt" if EMD Required=No, the numeric string if an amount is present,
    or None if neither field is found (e.g. low text-yield PDF).
    Commas stripped from the amount value.
    """
    amt_m = _EMD_AMT_RE.search(text)
    if amt_m:
        return amt_m.group(1).replace(",", "").strip()
    req_m = _EMD_REQ_RE.search(text)
    if req_m and req_m.group(1).lower() == "no":
        return "Exempt"
    return None


def _handle_single_tender(bid: dict, vendor: str, pdf_bytes: bytes) -> dict:
    """
    Route single-tender bids without an LLM call.
    - Teclever bid → score 5, PURSUE
    - Other vendor  → score 0, DECLINE with vendor name
    """
    is_ours = "teclever" in vendor.lower()

    if is_ours:
        print(f"  [single tender] Restricted to Teclever — auto-scoring 5 / PURSUE")
        bid.update({
            "pass2_score":          5,
            "pass2_confidence":     "High",
            "pass2_domain":         "Single Tender",
            "pass2_rationale":      "Single tender restricted exclusively to Teclever.",
            "pass2_gaps":           "None",
            "pass2_recommendation": "PURSUE",
        })
    else:
        print(f"  [single tender] Restricted to {vendor} — auto-declining")
        bid.update({
            "pass2_score":          0,
            "pass2_confidence":     "High",
            "pass2_domain":         "N/A",
            "pass2_rationale":      f"Single tender — restricted to: {vendor}. Teclever cannot participate.",
            "pass2_gaps":           "N/A",
            "pass2_recommendation": "DECLINE",
        })

    _save_pdf(pdf_bytes, bid["bid_number"], bid["pass2_recommendation"])
    return bid


def score_bid_pass2(bid: dict, capability_ref: str) -> dict:
    """Download PDF and run strict Pass 2 scoring via Sonnet."""
    from config import ANTHROPIC_API_KEY
    from modules.db import set_pass2_attempted

    # Mark as attempted immediately — prevents retry on next run regardless of outcome
    set_pass2_attempted(bid["bid_number"])

    try:
        pdf_bytes = download_pdf(bid["internal_id"])
    except Exception as e:
        print(f"  [warn] PDF download failed for {bid.get('bid_number')}: {e}")
        return bid

    extracted_text = extract_and_clean(pdf_bytes)

    # Extract EMD amount before any early return so it's always captured
    bid["emd_amount"] = extract_emd_amount(extracted_text)

    # Fetch supplementary spec docs before single-tender check (no LLM cost)
    spec_texts = _fetch_spec_texts(pdf_bytes, bid["bid_number"])

    # Single tender: route without LLM call
    m = _SINGLE_TENDER_PREFIX_RE.match(extracted_text)
    if m:
        return _handle_single_tender(bid, m.group(1).strip(), pdf_bytes)

    if spec_texts:
        spec_section = "\n\n---\nAdditional specification/scope documents:\n"
        for i, t in enumerate(spec_texts, 1):
            spec_section += f"\n[Document {i}]\n{t}\n"
        combined_text = extracted_text + spec_section
        print(f"  [spec] {len(spec_texts)} supplementary doc(s) added ({len(combined_text)} chars total)")
    else:
        combined_text = extracted_text

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = (
        "You are evaluating a Government e-Marketplace bid document for Teclever. "
        "Read the full document carefully. Then score it strictly using the "
        "capability reference system prompt. "
        "This is a STRICT evaluation — use precise evidence from the document text.\n\n"
        "Respond in exactly the required format:\n"
        "SCORE: [0-5]\n"
        "CONFIDENCE: [High/Medium/Low]\n"
        "DOMAIN MATCH: [...]\n"
        "MATCHING TECH: [...]\n"
        "GAPS: [...]\n"
        "RATIONALE: [...]\n"
        "RECOMMENDATION: [PURSUE | PURSUE WITH RAMP-UP | ASSESS FURTHER | DECLINE]"
    )
    if len(combined_text) >= _MIN_TEXT_CHARS:
        print(f"  [pdf] text extracted ({len(combined_text)} chars) — sending as text")
        content = [{"type": "text", "text": f"Bid document:\n\n{combined_text}\n\n{prompt}"}]
    else:
        print(f"  [pdf] low text yield ({len(combined_text)} chars) — sending as native PDF")
        pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
        content = [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}},
            {"type": "text", "text": prompt}
        ]

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            system=[{"type": "text", "text": capability_ref, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.APIStatusError as e:
        if e.status_code == 529:
            print(f"  [warn] Anthropic API overloaded — skipping {bid.get('bid_number')}")
            return bid
        err_str = str(e).lower()
        if e.status_code in (400, 429) and ("billing" in err_str or "usage limit" in err_str or "spend limit" in err_str):
            print("[STOP] Monthly spend limit reached — halting run.")
            sys.exit(1)
        raise
    except anthropic.APIConnectionError:
        print(f"  [warn] Connection error — skipping {bid.get('bid_number')}")
        return bid

    from modules.scorer_pass1 import parse_score_response
    parsed = parse_score_response(response.content[0].text)
    # Rename keys from pass1_* to pass2_*
    pass2 = {f"pass2_{k[6:]}": v for k, v in parsed.items()}
    # Add recommendation — fall back to score-derived value if missing
    m = re.search(r"RECOMMENDATION:\s*(.+)", response.content[0].text, re.IGNORECASE)
    if m:
        pass2["pass2_recommendation"] = m.group(1).strip()
    else:
        score = pass2.get("pass2_score", 0)
        if score >= 4:
            pass2["pass2_recommendation"] = "PURSUE"
        elif score == 3:
            pass2["pass2_recommendation"] = "ASSESS FURTHER"
        else:
            pass2["pass2_recommendation"] = "DECLINE"
        print(f"  [warn] RECOMMENDATION missing from response — derived '{pass2['pass2_recommendation']}' from score {score}")

    bid.update(pass2)
    _save_pdf(pdf_bytes, bid["bid_number"], pass2["pass2_recommendation"])
    return bid

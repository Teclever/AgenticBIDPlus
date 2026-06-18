"""HAL tenders portal adapter — the only module that knows the portal's API/URLs.

Targets the HAL corporate tenders site (https://hal-india.co.in/tender), served
by a WordPress REST backend behind a WAF. Every call needs browser-like headers
and cookies warmed from the tender page. The list endpoint returns ~160 tenders
in one POST (no server pagination); detail/document data is fetched lazily per
tender (Pass 1 enrichment / Pass 2 candidates). To support a different portal,
replace this module; everything else is portal-agnostic.
"""

from __future__ import annotations

import re

import requests

from config import (
    HAL_DETAIL_ENDPOINT,
    HAL_LIST_ENDPOINT,
    HAL_SITE_URL,
    HAL_TENDER_PAGE_URL,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
)
from modules.logutil import log_info, log_step, log_warn

PROGRESS_EVERY = 25

# Placeholder document URLs have no filename (end at the upload dir) — skip them.
_PLACEHOLDER_SUFFIX = "/uploads/tender/"


def make_session() -> requests.Session:
    """Build a session with browser headers and WAF cookies warmed.

    The HAL site sits behind a WAF that blocks bare requests; a browser-like
    User-Agent plus Referer/Origin/X-Requested-With headers and cookies obtained
    by first GET-ing the tender page are required on every API call.
    """
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Referer": HAL_TENDER_PAGE_URL,
            "Origin": HAL_SITE_URL,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/plain, */*",
        }
    )
    try:
        # Warm WAF cookies; failure here is non-fatal (API calls may still work).
        s.get(HAL_TENDER_PAGE_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 — cookie warming is best-effort
        log_warn(f"Could not warm WAF cookies from {HAL_TENDER_PAGE_URL}: {exc}")
    return s


def _post_results(session: requests.Session, url: str, files: dict) -> dict | None:
    """POST a multipart form and return the first record in `results`, or None.

    Private helper shared by the detail-fetching functions. Defensive against WAF
    blocks, non-JSON bodies, and missing/empty `results`.
    """
    try:
        resp = session.post(url, files=files, timeout=REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 — defensive against WAF/JSON failures
        log_warn(f"POST {url} failed: {exc}")
        return None
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or not results:
        return None
    first = results[0]
    return first if isinstance(first, dict) else None


def _post_all_results(session: requests.Session, url: str, files: dict) -> list[dict]:
    """POST a multipart form and return the full `results` list (empty on failure)."""
    try:
        resp = session.post(url, files=files, timeout=REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        log_warn(f"POST {url} failed: {exc}")
        return []
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []
    return [r for r in results if isinstance(r, dict)]


def _clean(value: object) -> str:
    """Strip HTML tags (e.g. <br/>) and collapse whitespace to a single line."""
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def _build_description(record: dict) -> str:
    """Join T_TITLE with T_DESC / T_REMARKS, but only when they add information."""
    title = _clean(record.get("T_TITLE"))
    parts = [title] if title else []
    seen = title.lower()
    for key in ("T_DESC", "T_REMARKS"):
        extra = _clean(record.get(key))
        if not extra:
            continue
        low = extra.lower()
        # Skip values that add nothing (already present in what we have so far).
        if low in seen:
            continue
        parts.append(extra)
        seen += " " + low
    return " — ".join(parts)


def _map_record(record: dict) -> dict | None:
    """Map a raw HAL listing record to our bid dict (per CONTRACT.md field map)."""
    tender_id = _clean(record.get("id"))
    if not tender_id:
        return None
    return {
        "tender_id": tender_id,
        "ref_no": _clean(record.get("T_REF_NO")),
        "center_name": _clean(record.get("Division_name")),
        "tender_description": _build_description(record),
        "bid_closing_date": _clean(record.get("T_BIDSUB_END_DATE")),
        "bid_opening_date": _clean(record.get("T_BID_OPEN_DATE")),
        "category": _clean(record.get("T_TENDER_CATEGORY_AS")),
    }


def fetch_listing(session: requests.Session | None = None) -> list[dict]:
    """Fetch and map the tender listing (one POST, no detail pages).

    POSTs an empty multipart form to the list endpoint and maps each raw HAL
    record to our bid dict. Detail text and document links are derived later,
    only for tenders that need them (Pass 1 enrichment / Pass 2 candidates).
    """
    owns_session = session is None
    session = session or make_session()
    try:
        log_info(f"Fetching tender listing: {HAL_LIST_ENDPOINT}")
        # `files=` forces a multipart/form-data POST (empty body); `data=` would not.
        results = _post_all_results(session, HAL_LIST_ENDPOINT, {"x": (None, "")})
        total = len(results)
        log_info(f"Received {total} raw record(s); mapping listing fields…")
        bids: list[dict] = []
        for i, record in enumerate(results, start=1):
            bid = _map_record(record)
            if not bid:
                continue
            bids.append(bid)
            if i % PROGRESS_EVERY == 0 or i == total:
                log_step(f"mapped {i}/{total} records ({len(bids)} valid tenders)")
        log_info(f"Parse complete: {len(bids)} tender(s) ready for database upsert.")
        return bids
    finally:
        if owns_session:
            session.close()


def fetch_detail_text(session: requests.Session, tender_id: str | None) -> str:
    """Return a compact labelled text block of useful detail fields, or "".

    The caller passes a numeric tender_id string (NOT a URL). POSTs the detail
    endpoint with multipart `id=<tender_id>` and assembles a labelled block for
    Pass 1 enrichment. Returns "" on any failure.
    """
    if not tender_id:
        return ""
    record = _post_results(session, HAL_DETAIL_ENDPOINT, {"id": (None, str(tender_id))})
    if not record:
        return ""
    # (label, raw HAL field) pairs for the most useful enrichment fields.
    field_map = [
        ("Reference No", "T_REF_NO"),
        ("Title", "T_TITLE"),
        ("Category", "T_TENDER_CATEGORY_AS"),
        ("Division", "Division_name"),
        ("Location", "T_LOCATION"),
        ("Inviting Officer", "T_INVITING_OFFICER"),
        ("Tender Fee", "T_TENDER_FEE"),
        ("EMD", "T_EMD"),
        ("Value", "T_TENDER_VALUE"),
        ("Currency", "T_CURRENCY"),
        ("Published Date", "T_PUBLISH_DATE"),
        ("Bid Open Date", "T_BID_OPEN_DATE"),
        ("Bid Submission End Date", "T_BIDSUB_END_DATE"),
        ("Description", "T_DESC"),
        ("Remarks", "T_REMARKS"),
    ]
    lines: list[str] = []
    for label, key in field_map:
        value = _clean(record.get(key))
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def collect_doc_links(session: requests.Session, bid: dict) -> list[str]:
    """Resolve downloadable document URLs for a single tender.

    POSTs the detail endpoint for `bid["tender_id"]` and returns the non-empty
    `tendorfile1..5` then `Corrigendum1..5` URLs, deduped and order-preserving.
    Placeholder URLs that end at the upload directory (no filename) are skipped.
    Called lazily at Pass 2 time, so it runs only for shortlisted candidates.
    """
    tender_id = bid.get("tender_id")
    if not tender_id:
        return []
    record = _post_results(session, HAL_DETAIL_ENDPOINT, {"id": (None, str(tender_id))})
    if not record:
        return []
    keys = [f"tendorfile{n}" for n in range(1, 6)] + [
        f"Corrigendum{n}" for n in range(1, 6)
    ]
    links: list[str] = []
    seen: set[str] = set()
    for key in keys:
        url = record.get(key)
        if not url:
            continue
        url = str(url).strip()
        if not url or url.endswith(_PLACEHOLDER_SUFFIX):
            continue
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links

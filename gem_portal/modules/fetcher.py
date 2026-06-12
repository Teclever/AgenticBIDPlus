import json, time, requests
from modules.csrf_handler import get_session

BASE_URL = "https://bidplus.gem.gov.in"


def search_bids(ministry: str, org: str, page: int,
                session: requests.Session, token: str) -> dict:
    payload = {
        "searchType": "ministry-search",
        "ministry": ministry,
        "organization": org,
        "department": "",
        "bidEndFromMin": "",
        "bidEndToMin": "",
        "page": page
    }
    data = {
        "payload": json.dumps(payload),
        "csrf_bd_gem_nk": token,
    }
    resp = session.post(f"{BASE_URL}/search-bids", data=data, timeout=20)
    resp.raise_for_status()

    # GeM returns a 200 HTML error page on CSRF failure — detect it explicitly
    if resp.headers.get("Content-Type", "").startswith("text/html"):
        from modules.csrf_handler import is_csrf_error
        if is_csrf_error(resp.text):
            raise RuntimeError(
                f"CSRF validation failed for {org}. "
                "Session may have expired — retry will re-handshake."
            )

    return resp.json()


def _first(val, default=""):
    """Extract first element if value is a list, else return as-is."""
    if isinstance(val, list):
        return val[0] if val else default
    return val if val is not None else default


def _parse_doc(doc: dict, ministry: str, org: str) -> dict:
    """Extract a bid dict from a raw API doc."""
    return {
        "bid_number":   _first(doc.get("b_bid_number", "")),
        "internal_id":  doc.get("id", ""),          # id is a plain string, not array
        "ministry":     _first(doc.get("ba_official_details_minName", ministry)),
        "organization": org,
        "department":   _first(doc.get("ba_official_details_deptName", "")),
        "items":        _first(doc.get("bbt_title", "")) or _first(doc.get("b_category_name", "")),
        "quantity":     _first(doc.get("b_total_quantity", 0)),
        "start_date":   _first(doc.get("final_start_date_sort", "")),
        "end_date":     _first(doc.get("final_end_date_sort", "")),
    }


def fetch_all_bids_for_org(ministry: str, org: str,
                            on_page=None) -> tuple[int, dict]:
    """
    Paginate ALL active bids for an org. No date filtering — every run is a full fetch.
    Stops only when the portal returns no more results (404/empty docs).

    Calls on_page(page_bids) after each page so the caller can upsert immediately.
    Returns (total_bid_count, metrics_dict).

    metrics["num_found"] is the portal's reported total for this org (from page 1).
    If total_bid_count < num_found, the portal silently truncated results — the caller
    should warn, as this indicates a portal-side pagination cap.
    """
    session, token = get_session()
    total         = 0
    pages_scanned = 0
    num_found     = 0
    ra_skipped    = 0
    page          = 1

    while True:
        data = search_bids(ministry, org, page, session, token)

        if data.get("code") == 404 or data.get("status") == 0:
            break

        inner = data.get("response", {}).get("response", {})
        docs  = inner.get("docs", [])
        if not docs:
            break

        if page == 1:
            num_found = inner.get("numFound", 0)

        pages_scanned += 1
        parsed = [_parse_doc(d, ministry, org) for d in docs]
        # GEM/yyyy/R/nnnn = Reverse Auction listings. RA participation is restricted
        # to bidders already qualified on the parent bid, and the showbidDocument
        # endpoint can't serve their documents — never ingest them.
        page_bids = [b for b in parsed if "/R/" not in (b["bid_number"] or "")]
        ra_skipped += len(parsed) - len(page_bids)

        if on_page:
            on_page(page_bids)
        total += len(page_bids)

        page += 1
        time.sleep(0.8)   # Polite delay — avoid triggering rate limits

    metrics = {"pages_scanned": pages_scanned, "num_found": num_found,
               "ra_skipped": ra_skipped}
    return total, metrics

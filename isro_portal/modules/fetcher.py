"""ISRO portal adapter — the only module that knows the portal's HTML/URLs.

Parses the `#tenderListTable` on the home page, enriches each row with detail
text (`/homeTenderView`) and document links (`/viewDocumentPT`,
`/viewCorrigendum`), and returns plain dicts for the DB layer to upsert. To
support a different portal, replace this module; everything else is portal-
agnostic. Built from the captured reference in `ISRO E Procurement.txt`.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import ISRO_BASE_URL, ISRO_HOME_URL, REQUEST_TIMEOUT_SECONDS, USER_AGENT
from modules.logutil import log_info, log_step, log_warn

PROGRESS_EVERY = 25


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def fetch_all_tenders(session: requests.Session | None = None) -> list[dict]:
    owns_session = session is None
    session = session or make_session()
    try:
        log_info(f"Fetching listing page: {ISRO_HOME_URL}")
        resp = session.get(ISRO_HOME_URL, timeout=REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        log_step(f"HTTP {resp.status_code} — parsing tender table…")
        soup = BeautifulSoup(resp.text, "lxml")
        table = soup.select_one("#tenderListTable")
        if table is None:
            raise RuntimeError("Could not find #tenderListTable on ISRO home page")
        body_rows = table.select("tbody tr")
        total_rows = len(body_rows)
        log_info(f"Found {total_rows} table row(s); enriching with detail/doc links…")
        bids: list[dict] = []
        for i, row in enumerate(body_rows, start=1):
            bid = _parse_row(row)
            if not bid:
                continue
            bid["detail_text"] = fetch_detail_text(session, bid.get("detail_url"))
            bid["doc_links_json"] = json.dumps(collect_doc_links(session, bid), ensure_ascii=True)
            bids.append(bid)
            if i % PROGRESS_EVERY == 0 or i == total_rows:
                log_step(f"enriched {i}/{total_rows} rows ({len(bids)} valid tenders)")
        log_info(f"Parse complete: {len(bids)} tender(s) ready for database upsert.")
        return bids
    finally:
        if owns_session:
            session.close()


def _parse_row(row) -> dict | None:
    cols = row.find_all("td")
    if len(cols) < 6:
        return None
    tender_id = cols[0].get_text(strip=True)
    if not tender_id:
        return None

    actions = cols[5]
    document_url = None
    detail_url = None
    corrigendum_url = None
    for link in actions.select("a"):
        href = link.get("href") or ""
        data_url = link.get("data-url") or ""
        text = link.get_text(" ", strip=True).lower()
        if "viewdocumentpt" in href.lower():
            document_url = _abs(href)
        if "hometenderview" in data_url.lower():
            detail_url = _abs(data_url)
        if "corrigendum" in data_url.lower() or "corrigendum" in text:
            corr = data_url or href
            corrigendum_url = _abs(corr)

    return {
        "tender_id": tender_id,
        "center_name": cols[1].get_text(" ", strip=True),
        "tender_description": cols[2].get_text(" ", strip=True),
        "bid_closing_date": cols[3].get_text(" ", strip=True),
        "bid_opening_date": cols[4].get_text(" ", strip=True),
        "document_url": document_url,
        "detail_url": detail_url,
        "corrigendum_url": corrigendum_url,
    }


def fetch_detail_text(session: requests.Session, detail_url: str | None) -> str:
    if not detail_url:
        return ""
    try:
        resp = session.get(detail_url, timeout=REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        return soup.get_text(" ", strip=True)
    except Exception:
        return ""


def collect_doc_links(session: requests.Session, bid: dict) -> list[str]:
    links: list[str] = []
    for url in (bid.get("document_url"), bid.get("corrigendum_url"), bid.get("detail_url")):
        if url:
            links.append(url)
    detail_url = bid.get("detail_url")
    if detail_url:
        try:
            resp = session.get(detail_url, timeout=REQUEST_TIMEOUT_SECONDS)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            for anchor in soup.select("a[href]"):
                href = anchor.get("href") or ""
                if re.search(r"(pdf|document|corrigendum|download)", href, flags=re.IGNORECASE):
                    links.append(_abs(href))
        except Exception:
            pass
    deduped = []
    seen = set()
    for link in links:
        if link and link not in seen:
            seen.add(link)
            deduped.append(link)
    return deduped


def _abs(path_or_url: str) -> str:
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        return path_or_url
    return urljoin(ISRO_BASE_URL, path_or_url)

"""HAL tender scraper — Playwright-based.

Tender list:  response listener captures jsonBusinessDatails / lmBusinessDatails JSON
              from Renderer network responses; no HTML-table parsing.
Documents:    gear-menu → VendorDocumentsController → DownloadController URLs
              collected by scanning all frames for onclick/href patterns.
Downloads:    context.request.get() so shared-session cookies are used automatically.

Critical: enc/chkSum URL params MUST stay percent-encoded (%3D / %26).
Decoding them (%3D → =, %26 → &) causes the server to reject the request.
"""

import json
import re
import time
from typing import Callable

from playwright.sync_api import BrowserContext, Page, TimeoutError as PWTimeout

from config import (
    BROWSER_PROFILE_DIR,
    HAL_BASE_URL,
    SCRAPE_DELAY_SECONDS,
    chromium_launch_args,
)

_ORIGIN = "https://eproc.hal-india.co.in"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Maps portal JSON field names → DB column names (listing fields only)
_FIELD_MAP: dict[str, str] = {
    "Buyer":                      "buyer",
    "Tender Number":              "tender_number",
    "Tender Description":         "tender_description",
    "Estimated Cost":             "estimated_cost",
    "Form Fee":                   "form_fee",
    "EMD":                        "emd_listing",
    "Tender Stage":               "tender_stage",
    "Tender Region":              "tender_region",
    "Tender Closing Date & Time": "closing_date",
    "Bidder Type(Nationality)":   "bidder_type",
}

_JSON_RECORDS_RE = re.compile(r"jsonBusinessDatails\s*=\s*'(\[.*?\])'\s*;", re.DOTALL)

_NA_VALUES = frozenset({"--NA--", "--na--", "N/A", "NA", "-- NA --"})


# ── URL helpers ────────────────────────────────────────────────────────────────

def _abs_download_url(raw: str) -> str:
    """Build an absolute DownloadController URL.

    enc/chkSum params MUST stay percent-encoded exactly as the portal emits them.
    Replace HTML-escaped & (&amp;) with %26, never with literal &.
    """
    raw = raw.replace("&amp;", "%26").strip()
    if raw.lower().startswith("http"):
        return raw
    if not raw.startswith("/"):
        raw = "/" + raw
    return _ORIGIN + raw


def _detail_url_from_line(line: str | None) -> str | None:
    """Extract the venderdisplayservlet URL from the 'Line Number' field.

    Format: '<line_no>$/$/$/ROOTAPP/servlet/venderdisplayservlet?enc%3D...%26chkSum%3D...'
    Params must stay percent-encoded; only the origin is prepended.
    """
    if not line:
        return None
    parts = line.split("$/$/$/")
    if len(parts) < 2 or not parts[1]:
        return None
    path = parts[1].strip()
    if path.lower().startswith("http"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return _ORIGIN + path


# ── JSON parsing ───────────────────────────────────────────────────────────────

def _parse_records_from_response(text: str) -> list[dict]:
    """Extract tender records from a Renderer network response.

    Handles two formats:
      - Paginated scroll response: JSON envelope with 'lmBusinessDatails' key
      - Initial search response:  HTML page with inline 'jsonBusinessDatails' variable
    """
    # Paginated JSON response
    try:
        obj = json.loads(text)
        for key in ("lmBusinessDatails", "sTenderHeaderDetails"):
            v = obj.get(key)
            if isinstance(v, str) and v.strip().startswith("["):
                arr = json.loads(v)
                if arr and isinstance(arr[0], dict) and "Serial Number" in arr[0]:
                    return arr
    except Exception:
        pass

    # HTML page with inline jsonBusinessDatails variable
    for m in _JSON_RECORDS_RE.finditer(text):
        try:
            return json.loads(m.group(1))
        except Exception:
            continue
    return []


def _build_record(j: dict) -> dict:
    """Normalise a portal JSON record to DB column names."""
    rec: dict = {}

    for src, dst in _FIELD_MAP.items():
        val = j.get(src)
        if isinstance(val, str):
            val = val.strip()
            if val in _NA_VALUES:
                val = ""
        rec[dst] = val

    # Line Number: "<line_no>$/$/$/ROOTAPP/servlet/venderdisplayservlet?..."
    line_raw = j.get("Line Number") or ""
    if "$/$/$/" in line_raw:
        parts = line_raw.split("$/$/$/", 1)
        rec["line_number"] = parts[0].strip()
        rec["detail_url"]  = _detail_url_from_line(line_raw)
    else:
        rec["line_number"] = line_raw.strip()
        rec["detail_url"]  = None

    return rec


def _seed_from_page(scope: Page, acc: dict[str, dict]) -> None:
    """Parse jsonBusinessDatails already embedded in the loaded page."""
    try:
        content = scope.content()
        for m in _JSON_RECORDS_RE.finditer(content):
            try:
                arr = json.loads(m.group(1))
                for rec in arr:
                    s = str(rec.get("Serial Number"))
                    if s and s != "None":
                        acc[s] = rec
            except Exception:
                continue
    except Exception:
        pass


def _get_total_count(scope: Page) -> int | None:
    try:
        m = re.search(r'"NO_OF_ROWS"\s*:\s*(\d+)', scope.content())
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


# ── Pagination helpers ─────────────────────────────────────────────────────────

def _first_row_signature(scope: Page) -> str | None:
    try:
        return scope.evaluate(
            "() => { const tr = document.querySelector('#myTable tbody tr'); "
            "return tr ? (tr.innerText || '').slice(0, 80) : null; }"
        )
    except Exception:
        return None


def _click_next(scope: Page) -> bool:
    """Click #scroll-right and wait for the table to change. Returns False if gone."""
    btn = scope.query_selector("#scroll-right")
    if not btn:
        return False
    before = _first_row_signature(scope)
    try:
        btn.click(timeout=5_000)
    except Exception:
        return False
    for _ in range(30):
        time.sleep(0.4)
        after = _first_row_signature(scope)
        if after and after != before:
            return True
    # Signature unchanged — stagnation logic in caller will stop the loop
    return True


# ── Full tender list collection ────────────────────────────────────────────────

def _collect_records_with_listener(
    context: BrowserContext,
    scope: Page,
    max_pages: int = 60,
    on_page: Callable[[list[dict]], None] | None = None,
) -> list[dict]:
    """Walk all pagination windows and collect every tender record.

    Attaches a context-level response listener to capture lmBusinessDatails /
    jsonBusinessDatails JSON from Renderer responses. Also seeds from the
    already-loaded first-window page content. Calls on_page(batch) with newly
    discovered records after each scroll so they can be upserted progressively.
    """
    total = _get_total_count(scope)
    print(f"  [fetch] Portal reports {total} total tender(s).", flush=True)

    json_acc: dict[str, dict] = {}

    def on_response(resp):
        try:
            url = resp.url
            if "Renderer" not in url and "UiRenderer" not in url:
                return
            text = resp.body().decode("utf-8", "replace")
            for rec in _parse_records_from_response(text):
                s = str(rec.get("Serial Number"))
                if s and s != "None":
                    json_acc[s] = rec
        except Exception:
            pass

    context.on("response", on_response)
    _seed_from_page(scope, json_acc)

    def _serial_key(s: str) -> int:
        try:
            return int(s)
        except Exception:
            return 10 ** 9

    reported: set[str] = set()

    def _flush(label: str) -> None:
        new_serials = set(json_acc.keys()) - reported
        if new_serials:
            new_recs = [_build_record(json_acc[s]) for s in sorted(new_serials, key=_serial_key)]
            if on_page:
                on_page(new_recs)
        reported.update(json_acc.keys())
        print(
            f"  [fetch] {label}: {len(json_acc)} record(s) captured so far",
            flush=True,
        )

    _flush("Window 1")

    stagnant   = 0
    last_count = len(json_acc)

    for page_idx in range(1, max_pages):
        if total and len(json_acc) >= total:
            print("  [fetch] All reported tenders captured.", flush=True)
            break
        if not _click_next(scope):
            print("  [fetch] Pagination control gone — stopping.", flush=True)
            break
        time.sleep(SCRAPE_DELAY_SECONDS)
        cur = len(json_acc)
        if cur == last_count:
            stagnant += 1
            if stagnant >= 4:
                print("  [fetch] No new records after 4 scrolls — stopping.", flush=True)
                break
        else:
            stagnant = 0
        last_count = cur
        _flush(f"Window {page_idx + 1}")

    try:
        context.remove_listener("response", on_response)
    except Exception:
        pass

    # Final flush for any records that arrived after the last scroll wait
    _flush("Final")

    return [_build_record(json_acc[s]) for s in sorted(json_acc, key=_serial_key)]


def fetch_all_tenders(
    on_page: Callable[[list[dict]], None] | None = None,
) -> int:
    """Scrape all active tenders using a persistent Playwright context.

    Flow: navigate to /HAL/ → click 'Go to Tender Free View' → click Search
    → response listener captures JSON from each Renderer page → scroll to end.

    Calls on_page(batch) after each pagination window so records can be
    upserted progressively. Returns the total number of unique tenders fetched.
    """
    from playwright.sync_api import sync_playwright
    from modules.session import open_free_view, find_results_scope

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE_DIR),
            headless=True,
            accept_downloads=True,
            ignore_https_errors=True,
            args=chromium_launch_args(),
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()

            print("  [fetch] Opening HAL portal…", flush=True)
            open_free_view(context, page)

            # find_results_scope handles clicking Search internally
            print("  [fetch] Waiting for results table…", flush=True)
            scope = find_results_scope(context)
            if scope is None:
                print("  [fetch] ERROR: results table never appeared.", flush=True)
                return 0

            records = _collect_records_with_listener(context, scope, on_page=on_page)
            return len(records)
        finally:
            context.close()


# ── Row finder (Pass 2) ────────────────────────────────────────────────────────

def find_tender_row(scope: Page, tender_number: str, max_windows: int = 20) -> int | None:
    """Find the row index (0-based) of a tender in the visible #myTable window.

    Scrolls forward through pagination windows until the tender number appears
    in a row's text. Stops when found or when #scroll-right disappears.
    Returns the row index within the current window, or None if not found.
    Leaves the table positioned at the window that contains the tender so that
    the caller can immediately click the gear on that row.
    """
    _FIND_JS = """(tn) => {
        const rows = document.querySelectorAll('#myTable tbody tr');
        for (let i = 0; i < rows.length; i++) {
            if ((rows[i].innerText || '').includes(tn)) return i;
        }
        return -1;
    }"""

    for _ in range(max_windows):
        try:
            idx = scope.evaluate(_FIND_JS, tender_number)
            if idx >= 0:
                return idx
        except Exception:
            pass
        if not _click_next(scope):
            break
        time.sleep(SCRAPE_DELAY_SECONDS)
    return None


# ── Document URL collection ────────────────────────────────────────────────────

def collect_download_urls(page: Page) -> set[str]:
    """Scan every frame of a page for DownloadController links in onclick/href."""
    urls: set[str] = set()
    for fr in page.frames:
        try:
            found = fr.evaluate(
                r"""() => {
                  const out = [];
                  const re = /(\/?(?:ROOTAPP\/servlet\/)?asl\.tw\.DownloadController\?[^\s"'<>\\)]+)/i;
                  const scan = (s) => { if (s) { const m = s.match(re); if (m) out.push(m[1]); } };
                  document.querySelectorAll('*').forEach(el => {
                    if (!el.getAttribute) return;
                    scan(el.getAttribute('onclick'));
                    scan(el.getAttribute('href'));
                  });
                  return out;
                }"""
            )
            for raw in found or []:
                urls.add(_abs_download_url(raw))
        except Exception:
            continue
    return urls


def open_tender_documents(
    context: BrowserContext,
    results_page: Page,
    row_idx: int,
) -> set[str]:
    """Click the row's Actions gear → 'Show tender documents' and return download URLs.

    Opens the VendorDocumentsController page (usually a new tab), collects all
    DownloadController URLs from every frame, then closes the tab.
    row_idx is 0-based; row 0 is the first result row in #myTable.
    """
    urls: set[str] = set()

    gear = results_page.query_selector(
        f"#myTable tbody tr:nth-child({row_idx + 1}) .setting-image2"
    )
    if not gear:
        print(f"  [fetch] Gear not found for row {row_idx}.", flush=True)
        return urls

    try:
        gear.click(timeout=5_000)
    except Exception as exc:
        print(f"  [fetch] Gear click error: {exc}", flush=True)
        return urls

    results_page.wait_for_timeout(1_800)

    # The dropdown menu container for this row
    container_sel = f"#HideSubmit1{row_idx}"
    try:
        item = results_page.locator(container_sel).get_by_text(
            "Show tender documents", exact=False
        ).first
        if item.count() == 0:
            item = results_page.get_by_text("Show tender documents", exact=False).first
    except Exception:
        item = results_page.get_by_text("Show tender documents", exact=False).first

    try:
        with context.expect_page(timeout=8_000) as pinfo:
            item.click(timeout=5_000)
        doc_page = pinfo.value
        doc_page.wait_for_load_state("domcontentloaded", timeout=30_000)
        doc_page.wait_for_timeout(2_500)
        urls |= collect_download_urls(doc_page)
        try:
            doc_page.close()
        except Exception:
            pass
    except PWTimeout:
        # Documents may render in-place instead of a new tab
        results_page.wait_for_timeout(2_000)
        urls |= collect_download_urls(results_page)
    except Exception as exc:
        print(f"  [fetch] Documents menu error: {exc}", flush=True)

    # Dismiss the open gear menu before returning
    try:
        results_page.keyboard.press("Escape")
    except Exception:
        pass

    return urls


# ── File download ──────────────────────────────────────────────────────────────

def download_document(context: BrowserContext, url: str, idx: int, seen_names: set[str]) -> tuple[bytes, str] | None:
    """Download a document via context.request.get() (shared session cookies).

    Returns (bytes, filename) or None if:
      - The response is an HTML page (viewer/error, not a real file)
      - The filename was already seen (portal exposes each file twice)
      - The HTTP request failed
    """
    try:
        resp = context.request.get(url, timeout=90_000)
    except Exception as exc:
        print(f"  [fetch] Download error for URL {idx}: {exc}", flush=True)
        return None

    if not resp.ok:
        print(f"  [fetch] HTTP {resp.status} for download {idx}", flush=True)
        return None

    ct = resp.headers.get("content-type", "")
    if ct.startswith("text/html"):
        # Viewer or error page — not an actual file
        return None

    # Determine filename from Content-Disposition
    disp = resp.headers.get("content-disposition", "")
    fname = None
    m = re.search(r'filename\*?=(?:UTF-8\'\'|)?"?([^";]+)"?', disp, re.IGNORECASE)
    if m:
        raw_name = m.group(1).strip()
        # Sanitise: keep alphanumeric, dots, dashes, underscores
        fname = re.sub(r"[^A-Za-z0-9._\-]+", "_", raw_name).strip("._")[:120]

    if not fname:
        ext  = ".pdf" if "pdf" in ct else (".doc" if "msword" in ct else ".bin")
        fname = f"document_{idx}{ext}"

    # Dedup: the portal exposes each file twice (attachment + inline)
    if fname in seen_names:
        return None
    seen_names.add(fname)

    return resp.body(), fname

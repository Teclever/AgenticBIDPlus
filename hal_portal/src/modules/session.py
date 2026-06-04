"""HAL portal navigation helpers — Playwright only, no plain-HTTP session."""

import time

from playwright.sync_api import BrowserContext, Page, TimeoutError as PWTimeout

from config import HAL_BASE_URL, SCRAPE_DELAY_SECONDS

_ENTRY_TEXTS = ["Go to Tender Free View", "Tender Free View", "Free View"]

_SEARCH_SELECTORS = [
    "#submitsearch",
    "input.SearchButton[onclick*='search']",
    "[onclick='search()']",
    "input[value='Submit'].SearchButton",
    "input[value='Search']",
]

# Candidate selectors for the tender-number filter field in the search form.
_TENDER_NUMBER_FIELD_SELECTORS = [
    "input[name='Tender']",
    "input[name='tendernumbersearch']",
    "#Tender",
    "input[placeholder*='Tender No' i]",
    "input[id*='TenderNo' i]",
    "input[name*='tender' i][type='text']",
]


def open_free_view(context: BrowserContext, page: Page) -> Page:
    """Navigate to HAL_BASE_URL and click 'Go to Tender Free View'.

    The portal home is an Aurelia SPA rendered inside a Mobility iframe.
    Clicking the entry link opens a new tab; returns that tab's Page.
    Falls back to the same page if no new tab appears.
    """
    page.goto(HAL_BASE_URL, wait_until="domcontentloaded", timeout=90_000)

    link = None
    for _ in range(40):
        for fr in page.frames:
            for text in _ENTRY_TEXTS:
                try:
                    loc = fr.get_by_text(text, exact=False)
                    if loc.count() > 0:
                        link = loc.first
                        break
                except Exception:
                    continue
            if link:
                break
        if link:
            break
        page.wait_for_timeout(1_000)

    if link is None:
        print("  [session] 'Tender Free View' entry not found — using current page.", flush=True)
        return page

    try:
        with context.expect_page(timeout=12_000) as pinfo:
            link.click(timeout=8_000)
        fv = pinfo.value
        fv.wait_for_load_state("domcontentloaded", timeout=60_000)
        return fv
    except PWTimeout:
        return page
    except Exception as exc:
        print(f"  [session] Entry click note: {exc}", flush=True)
        return page


def fill_tender_number(scope: Page, tender_number: str) -> bool:
    """Fill the tender number filter field in the search form.

    Strategy (in order):
      1. Wait for #submitsearch so the form is fully rendered.
      2. Try known CSS selectors across every frame.
      3. JS regex scan of all <input> elements across every frame.
      4. On total failure, log available inputs for diagnosis.
    Returns True if a field was filled.
    """
    # Wait for the form submit button as a proxy for the form being ready
    try:
        scope.wait_for_selector("#submitsearch", timeout=8_000)
    except Exception:
        pass

    # Pass 1: known selectors in every frame
    for fr in scope.frames:
        for sel in _TENDER_NUMBER_FIELD_SELECTORS:
            try:
                el = fr.query_selector(sel)
                if el:
                    el.fill(tender_number)
                    return True
            except Exception:
                continue

    # Pass 2: JS regex scan — matches any input whose name/id/placeholder looks
    # like a tender-number field.
    for fr in scope.frames:
        try:
            result = fr.evaluate(
                """(tn) => {
                    const re = /tender|tndno|tno/i;
                    for (const inp of document.querySelectorAll(
                            'input[type="text"], input:not([type])')) {
                        const n  = inp.name        || '';
                        const id = inp.id          || '';
                        const ph = inp.placeholder || '';
                        if (re.test(n) || re.test(id) || re.test(ph)) {
                            inp.value = tn;
                            inp.dispatchEvent(new Event('input',  {bubbles: true}));
                            inp.dispatchEvent(new Event('change', {bubbles: true}));
                            return {found: true, name: n, id: id};
                        }
                    }
                    return {found: false};
                }""",
                tender_number,
            )
            if result and result.get("found"):
                print(
                    f"  [session] Filled tender number via JS "
                    f"(name={result.get('name')!r} id={result.get('id')!r})",
                    flush=True,
                )
                return True
        except Exception:
            continue

    # Diagnostic dump so we can identify the correct selector next time
    try:
        fields = scope.evaluate(
            "() => Array.from(document.querySelectorAll('input')).map(i => "
            "({name: i.name, id: i.id, type: i.type, ph: i.placeholder}))"
        )
        print(
            f"  [session] fill_tender_number: no field found. "
            f"Inputs on page: {fields[:12]}",
            flush=True,
        )
    except Exception:
        pass

    return False


def click_search(context: BrowserContext) -> bool:
    """Click the Search/Submit button on any open page. Returns True if clicked."""
    for pg in list(context.pages):
        for sel in _SEARCH_SELECTORS:
            try:
                btn = pg.query_selector(sel)
                if btn:
                    btn.click(timeout=4_000)
                    return True
            except Exception:
                continue
        # Fall back to calling the portal's own search() JS function
        try:
            if pg.evaluate("() => typeof search === 'function' ? (search(), true) : false"):
                return True
        except Exception:
            continue
    return False


def find_results_scope(context: BrowserContext, timeout_ms: int = 90_000) -> Page | None:
    """Wait for #myTable to appear, clicking Search if it hasn't been submitted yet.

    Mirrors the POC's find_results_scope: on the first iteration, if #myTable
    is not present, try clicking the Search button (or invoking search() via JS)
    so the results table eventually loads. Polls every 1.5 s.

    Returns a Page (not a Frame) — pagination reloads the page which detaches
    Frame handles, so callers must hold a Page reference.
    """
    deadline = time.time() + timeout_ms / 1_000
    searched = False

    while time.time() < deadline:
        # Check every open page for the results table
        for pg in list(context.pages):
            try:
                if pg.query_selector("#myTable tbody tr"):
                    return pg
            except Exception:
                continue

        # Results not visible yet — click Search once
        if not searched:
            for pg in list(context.pages):
                for sel in _SEARCH_SELECTORS:
                    try:
                        btn = pg.query_selector(sel)
                        if btn:
                            btn.click(timeout=4_000)
                            searched = True
                            print(f"  [session] Clicked search: {sel}", flush=True)
                            break
                    except Exception:
                        continue
                if searched:
                    break

            if not searched:
                for pg in list(context.pages):
                    try:
                        if pg.evaluate(
                            "() => typeof search === 'function' ? (search(), true) : false"
                        ):
                            searched = True
                            print("  [session] Invoked search() via JS.", flush=True)
                            break
                    except Exception:
                        continue

        time.sleep(1.5)

    return None

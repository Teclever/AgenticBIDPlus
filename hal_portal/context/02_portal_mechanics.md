# HAL Portal — Scrape Mechanics (Playwright)

> **Implementation note.** This document describes the **current implementation**,
> which drives a headless Chromium browser via **Playwright**. An earlier design
> (preserved in this file's git history) planned a plain-HTTP `requests.Session`
> "8-step enc/chkSum chain". That approach was **abandoned** — the portal's
> Aurelia SPA front end and session-bound `enc`/`chkSum` tokens made full browser
> automation far more robust. There is no `requests` code path anywhere in the
> tool. The schema/pipeline *logic* in the sibling docs remains valid; only the
> transport mechanism changed.

## Platform
TenderWizard (C1 India / Antares Systems), fronted by an **Aurelia single-page
app** served from `https://eproc.hal-india.co.in/HAL/` and rendered inside a
"Mobility" iframe. All in-portal navigation uses encrypted `enc` + `chkSum`
tokens that are **session-specific and server-generated** — they cannot be
constructed offline. Rather than chase those tokens by hand, the tool lets a real
browser session generate and carry them.

- **Entry URL** (`config.HAL_BASE_URL`): `https://eproc.hal-india.co.in/HAL/`
- **Origin** (`fetcher._ORIGIN`): `https://eproc.hal-india.co.in`

## Session & browser profile
The tool launches a **persistent** Playwright Chromium context
(`pw.chromium.launch_persistent_context`):

| Setting | Value |
|---------|-------|
| `user_data_dir` | `BROWSER_PROFILE_DIR` = `.browser_profile/` (gitignored, regenerated per machine) |
| `headless` | `True` |
| `accept_downloads` | `True` |
| `ignore_https_errors` | `True` |
| `args` | `config.chromium_launch_args()` |

- Cookies (`JSESSIONID`, etc.) and storage **persist across runs**, so the portal
  session stays warm between the scrape and the Pass 2 document fetch — no
  re-authentication needed.
- **No login, no CAPTCHA** — the entire portal, including PDF downloads, is
  publicly accessible. `JSESSIONID` is auto-issued on first navigation.
- `chromium_launch_args()` probes the portal host's A-records at launch and pins
  Chromium to the first reachable IP via `--host-resolver-rules=MAP <host> <ip>`.
  The host publishes several A-records and occasionally leaves one dead; headless
  Chromium (unlike curl) does not fail over and would hang the full navigation
  timeout on a dead IP. It also sets `--disable-blink-features=AutomationControlled`.

---

## Scrape flow (`modules/session.py`, `modules/fetcher.py`)

The list scrape is **driven by clicks and captured from network responses** — it
never parses the visible HTML table. Entry point: `fetcher.fetch_all_tenders()`.

### Step 1 — Open the Free View (`session.open_free_view`)
1. `page.goto(HAL_BASE_URL)`.
2. Poll every frame for a link whose text matches one of
   `"Go to Tender Free View"`, `"Tender Free View"`, `"Free View"`.
3. Click it. The portal opens the search form in a **new tab**; that tab's `Page`
   is returned (falls back to the same page if no new tab appears).

### Step 2 — Submit the search (`session.find_results_scope`)
`find_results_scope(context)` polls all open pages for `#myTable tbody tr`. On the
first pass, if the results table is not present yet, it clicks the Search button
(trying selectors `#submitsearch`, `input.SearchButton[onclick*='search']`,
`[onclick='search()']`, …) or, as a fallback, invokes the portal's own `search()`
JS function. It returns a **`Page`** (not a `Frame`) because pagination reloads the
page and detaches frame handles. The default search returns **all active
tenders** — no buyer/stage/bidder filter is applied in the UI default.

### Step 3 — Capture tender JSON from network responses (`_collect_records_with_listener`)
A **context-level response listener** is attached for the duration of the scrape:

```python
def on_response(resp):
    if "Renderer" not in resp.url and "UiRenderer" not in resp.url:
        return
    text = resp.body().decode("utf-8", "replace")
    for rec in _parse_records_from_response(text):
        json_acc[str(rec["Serial Number"])] = rec
```

`_parse_records_from_response` handles **two response shapes**:

| Shape | Where it appears | How it is parsed |
|-------|------------------|------------------|
| HTML page with an inline `jsonBusinessDatails = '[…]';` JS variable | initial search result page | regex `_JSON_RECORDS_RE` |
| JSON envelope with a `lmBusinessDatails` (or `sTenderHeaderDetails`) string key holding a JSON array | paginated scroll responses | `json.loads`, then verify `arr[0]` has a `"Serial Number"` key |

The first-window page is **also** seeded directly via `_seed_from_page(scope,
json_acc)`. Records are de-duplicated by their `"Serial Number"` value.

### Step 4 — Paginate by scrolling (`_click_next`)
There is no page-number control; results load in windows via an infinite-scroll
button `#scroll-right`:
1. Record the first row's text signature (`#myTable tbody tr` innerText, first 80 chars).
2. Click `#scroll-right`; wait up to ~12 s for the signature to change.
3. The response listener captures each new window's JSON automatically.

**Stop conditions** (any one): `len(json_acc) >= NO_OF_ROWS` (total scraped from
`"NO_OF_ROWS"` in the page content), `#scroll-right` disappears, no new records
after 4 consecutive scrolls (`stagnant >= 4`), or `max_pages` (60) reached.
`SCRAPE_DELAY_SECONDS` (0.7 s) throttles between scrolls.

### Step 5 — Progressive upsert
After each window, newly-seen serials are converted to DB records and handed to an
`on_page(batch)` callback, which the CLI wires to `db.upsert_raw_tender`. The DB
fills incrementally, so a mid-scrape crash still persists everything captured so
far. `fetch_all_tenders` returns the total count of unique tenders.

---

## Tender record fields (`_FIELD_MAP`, `_build_record`)

Each captured JSON record is normalised to DB columns. Values in
`{"--NA--", "N/A", "NA", "-- NA --", …}` (`_NA_VALUES`) are blanked to `""`.

| Portal JSON field | DB column |
|-------------------|-----------|
| `Buyer` | `buyer` (IMM / WORKS / OUTSOURCING) |
| `Tender Number` | `tender_number` (primary identifier) |
| `Tender Description` | `tender_description` |
| `Estimated Cost` | `estimated_cost` (e.g. `RS1,27,89,00,000.00` or `RS0`) |
| `Form Fee` | `form_fee` |
| `EMD` | `emd_listing` (often `RS0` / `--NA--`) |
| `Tender Stage` | `tender_stage` (Latest / Opened / Awarded / …) |
| `Tender Region` | `tender_region` (HAL division, e.g. `Design Complex -MCSRDC`) |
| `Tender Closing Date & Time` | `closing_date` (`dd-mm-yyyy HH:MM`) |
| `Bidder Type(Nationality)` | `bidder_type` (Both / Indian / Foreign) |
| `Serial Number` | (de-dup key only, not stored) |
| `Line Number` | split → `line_number` + `detail_url` (see below) |

**Line Number format:**
`"<line_no>$/$/$/ROOTAPP/servlet/venderdisplayservlet?enc%3D…%26chkSum%3D…"`
Split on `$/$/$/`: left half = `line_number`; right half = the
`venderdisplayservlet` detail-page path, turned into an absolute URL in
`detail_url` (origin prepended). The composite **primary key is
`(tender_number, line_number)`** — one tender number can have multiple line numbers.

> ⚠️ **`enc`/`chkSum` must stay percent-encoded** (`%3D`, `%26`). Decoding them to
> `=`/`&` causes the server to reject the request. `_abs_download_url` replaces
> `&amp;` with `%26`, never with a literal `&`.

> **Note — unused schema columns.** The current scraper's `_FIELD_MAP` captures
> only the 10 listing fields above. The richer columns in the schema
> (`tender_cover`, `announcement_date`, `tender_type`, `submission_type`,
> `tender_for`, `directory_id`, `issue_date_from`, `issue_date_to`, and the
> detail-page fields `opening_date`, `cost_open_date`, `tender_mode`,
> `validity_of_bid`, `contact_email`, `contact_person`, `qualification_criteria`,
> `additional_notes`) exist (added by `db._migrate`) but are **not populated** by
> the current implementation — there is no detail-page or pagination-JSON field
> extraction in the live code path. They remain available for a future enhancement.

---

## Document retrieval (Pass 2) — `fetcher.open_tender_documents`, `fetcher.download_document`

Per shortlisted tender (one shared search page is reused across all tenders within
a Pass 2 run — see `scorer_pass2.score_tender_pass2`):

1. **Reset & filter** — reload the search page to its empty-form URL, fill the
   tender-number field (`session.fill_tender_number`, which tries known selectors
   then a JS regex scan across all frames), click Search.
2. **Locate the row** — `fetcher.find_tender_row` scans `#myTable` rows for the
   tender number, scrolling forward through windows if needed. (The text filter
   does not always narrow to one result, so the row index is found explicitly.)
3. **Open the documents view** — click the row's Actions gear (`.setting-image2`)
   → "Show tender documents". This usually opens the `VendorDocumentsController`
   page in a **new tab**; if it renders in place, the current page is scanned.
4. **Collect download URLs** — `collect_download_urls` scans **every frame** of the
   documents page for `asl.tw.DownloadController?…` URLs in any element's
   `onclick`/`href` attribute.
5. **Download** — each URL is fetched with `context.request.get(url)` so the shared
   browser session cookies are sent automatically. `download_document`:
   - skips responses whose `content-type` is `text/html` (a viewer/error page, not
     a real file);
   - derives the filename from `Content-Disposition`, sanitising to
     `[A-Za-z0-9._-]`, capped at 120 chars;
   - **de-duplicates by filename** — the portal exposes each file twice
     (attachment + inline), so the second copy is dropped.

GeM-routed tenders legitimately have **no attachments**; that is a valid outcome,
and Pass 2 still scores them from listing data alone. Only popup pages opened
during a tender's document fetch are closed afterwards; the shared search page
stays open for the next tender.

### Quick reference — key selectors & tokens

| Thing | Value |
|-------|-------|
| Entry link text | `Go to Tender Free View` (and fallbacks) |
| Search button | `#submitsearch` / `input.SearchButton` / `search()` JS |
| Results table | `#myTable tbody tr` |
| Next-window button | `#scroll-right` |
| Row Actions gear | `#myTable tbody tr:nth-child(N) .setting-image2` |
| Documents menu item | text `Show tender documents` (container `#HideSubmit1{row}`) |
| Total-count source | `"NO_OF_ROWS"` in page content |
| Download URL pattern | `asl.tw.DownloadController?enc=…&chkSum=…` |
| Detail URL pattern | `venderdisplayservlet?enc=…&chkSum=…` (from Line Number) |
| Response-listener match | URL contains `Renderer` or `UiRenderer` |

---

## Reference values (from listing data)

**Buyer** (`buyer` column) — the portal exposes IMM, WORKS, and OUTSOURCING
buyers. The tool's default search applies **no buyer filter**, so all three are
captured in one sweep:

| Buyer | Meaning |
|-------|---------|
| `IMM` | Inventory / materials management |
| `WORKS` | Civil / infrastructure works |
| `OUTSOURCING` | Job work / outsourced manufacturing |

**Tender Stage** (`tender_stage` column): `Latest` (active, pre-opening),
`Opened` (bids opened), `Awarded`, `Declined`, `Archived`. The default search
returns active tenders; the `db.sweep_closed_tenders` step then flips any whose
`closing_date` is before today to `bid_status = CLOSED`.

## Important Notes
- `enc` + `chkSum` tokens are **session-specific** — generated and carried by the
  live browser session; never cached across runs or constructed by hand.
- Keep `enc`/`chkSum` **percent-encoded** end-to-end (`%3D`, `%26`).
- The list scrape reads tender JSON from **network responses**
  (`Renderer`/`UiRenderer` URLs), not from the visible HTML table.
- The persistent browser profile (`.browser_profile/`) keeps the `JSESSIONID`
  session warm between the scrape and the Pass 2 document fetch.
- Documents are downloaded with `context.request.get()` so the browser session
  cookies are reused automatically — no separate auth.
- Tender numbers contain `/`, which must be sanitised to `_` for folder/filenames.
- Total active tenders observed: **~143** (`NO_OF_ROWS`, 2026-05-30) — varies daily.

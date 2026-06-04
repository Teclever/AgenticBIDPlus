# HAL Tool — Database Schema, Excel Formats, and Pipeline

## Database Schema (SQLite)

HAL-specific schema — not a 1:1 copy of GEM. Will be revisited during implementation if new fields are discovered. Use `_migrate()` pattern from GEM for safe column additions post-launch.

**Primary key:** `(tender_number, line_number)` composite.

```sql
CREATE TABLE tenders (
    -- Identity
    tender_number           TEXT NOT NULL,
    line_number             TEXT NOT NULL,

    -- Listing fields (from jsonBusinessDatails — Step 4 of scrape)
    buyer                   TEXT,       -- IMM / WORKS / OUTSOURCING
    tender_description      TEXT,       -- short description of work
    estimated_cost          TEXT,       -- often RS0 for IMM/outsourcing tenders
    form_fee                TEXT,
    emd_listing             TEXT,       -- EMD from listing; often RS0 or --NA--

    tender_stage            TEXT,       -- Latest / Opened / Awarded / etc.
    tender_region           TEXT,       -- HAL division name
    bidder_type             TEXT,       -- Both / Indian / Foreign
    closing_date            TEXT,       -- dd-mm-yyyy HH:MM

    -- Additional listing fields (from TenderDetails in Step 5 pagination JSON)
    tender_cover            TEXT,       -- TENDERSTAGE: onestage / Twostage
    announcement_date       TEXT,       -- TEND_AUTH_DATE: dd-mm-yyyy HH:MM:SS
    tender_type             TEXT,       -- TENDER_TYPE_ID: Open / Limited
    submission_type         TEXT,       -- MANUALTENDERFLAG: Online / Manual
    tender_for              TEXT,       -- TENDER_FOR: Domestic / International
    directory_id            INTEGER,    -- DIRECTORY: portal internal record ID
    issue_date_from         TEXT,       -- ISSUEOFTENDDOCFROMDATE: dd-mm-yyyy HH:MM
    issue_date_to           TEXT,       -- ISSUEOFTENDDOCTODATE: dd-mm-yyyy HH:MM

    -- Detail page fields (from Step 6 — only these still require the detail page fetch)
    opening_date            TEXT,       -- techno-commercial open date
    cost_open_date          TEXT,
    tender_mode             TEXT,       -- IMM / WORKS / OUTSOURCING (from detail)
    validity_of_bid         TEXT,
    contact_email           TEXT,
    contact_person          TEXT,
    qualification_criteria  TEXT,
    additional_notes        TEXT,

    -- PDF-extracted financial values (populated during Pass 2)
    emd_amount              TEXT,       -- precise EMD from RFQ PDF (more reliable than emd_listing)
    contract_value          TEXT,       -- total project/contract value from RFQ PDF

    -- Pass 1 scoring (Haiku)
    pass1_score             INTEGER,
    pass1_confidence        TEXT,       -- High / Medium / Low
    pass1_domain            TEXT,
    pass1_rationale         TEXT,
    pass1_gaps              TEXT,

    -- Pass 2 scoring (Sonnet)
    pass2_score             INTEGER,
    pass2_confidence        TEXT,
    pass2_domain            TEXT,
    pass2_rationale         TEXT,
    pass2_gaps              TEXT,
    pass2_recommendation    TEXT,       -- PURSUE / PURSUE WITH RAMP-UP / ASSESS FURTHER / DECLINE

    -- Human review columns
    human_override_score    INTEGER,
    human_override_reason   TEXT,
    run_pass2               INTEGER DEFAULT 0,  -- 0=auto-threshold, 1=force-yes, -1=force-no

    -- Pass 2 execution tracking
    pass2_attempted         INTEGER DEFAULT 0,  -- 1 = attempted (even if failed); prevents endless retry

    -- Lifecycle
    bid_status              TEXT DEFAULT 'NEW', -- NEW / ACTIVE / EXTENDED / CLOSED
    previous_closing_date   TEXT,               -- saved when deadline extends
    extension_count         INTEGER DEFAULT 0,
    first_seen_date         TEXT,
    last_seen_at            TEXT,
    last_updated_date       TEXT,
    pass1_exported          INTEGER DEFAULT 0,  -- 1 = included in a pass1 delta file

    PRIMARY KEY (tender_number, line_number)
);

CREATE TABLE excel_log (
    filename            TEXT PRIMARY KEY,   -- e.g. pass1_2026-05-30.xlsx
    ingested_date       TEXT,
    overrides_found     INTEGER,
    overrides_applied   INTEGER
);

CREATE TABLE feedback (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    tender_number       TEXT,
    line_number         TEXT,
    original_score      INTEGER,
    corrected_score     INTEGER,
    reason              TEXT,
    promoted_to_rule    INTEGER DEFAULT 0,
    created_date        TEXT
);

CREATE TABLE few_shot_examples (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tender_title    TEXT,
    correct_score   INTEGER,
    reason          TEXT,
    created_date    TEXT
);
```

**No `exclusion_rules` table** — pass 1 score/recommendation is the sole gatekeeper for pass 2.

---

## PDF Financial Extraction (Pass 2)

Extracted from RFQ and technical PDFs using regex on cleaned text:

- **`emd_amount`** — Search for: `EMD`, `Earnest Money Deposit`, `Security Deposit` near a rupee/numeric value. Stored in DB; shown in pass2 Excel. More reliable than `emd_listing`.
- **`contract_value`** — Search for: `Estimated Cost`, `Estimated Value`, `Total Value`, `Contract Value`, `Project Value`, `Total Project Cost` near a rupee/numeric value. NULL if not found.

Both give reviewers the financial context for a proper go/no-go judgment alongside the capability score.

---

## Excel Column Mappings

### pass1_YYYY-MM-DD.xlsx (Sheet: Pass1)
Daily review file. Contains all newly-scored tenders plus any EXTENDED ones.

| Column | DB Field |
|--------|----------|
| Tender Number | `tender_number` |
| Line Number | `line_number` |
| Buyer | `buyer` |
| Region | `tender_region` |
| Tender Description | `tender_description` |
| Estimated Cost | `estimated_cost` |
| Closing Date | `closing_date` |
| Pass 1 Score | `pass1_score` |
| Pass 1 Confidence | `pass1_confidence` |
| Pass 1 Domain | `pass1_domain` |
| Pass 1 Rationale | `pass1_rationale` |
| Pass 2 Score | `pass2_score` |
| Pass 2 Confidence | `pass2_confidence` |
| Pass 2 Domain | `pass2_domain` |
| Pass 2 Rationale | `pass2_rationale` |
| Pass 2 Recommendation | `pass2_recommendation` |
| EMD (Listing) | `emd_listing` |
| **Run Pass 2** | `run_pass2` — human edits Y/N here |
| **Human Override Score** | `human_override_score` — human edits here |
| **Human Override Reason** | `human_override_reason` — human edits here |
| Bid Status | `bid_status` |
| Extension Count | `extension_count` |
| First Seen | `first_seen_date` |

**Bold columns** = human-editable. Ingest reads these back into DB.

### pass2_YYYY-MM-DD.xlsx (Sheet: Pass2)
Daily pass 2 results file. Contains only tenders scored in this pass 2 run.

| Column | DB Field |
|--------|----------|
| Tender Number | `tender_number` |
| Line Number | `line_number` |
| Buyer | `buyer` |
| Region | `tender_region` |
| Tender Description | `tender_description` |
| Closing Date | `closing_date` |
| Pass 2 Score | `pass2_score` |
| Pass 2 Confidence | `pass2_confidence` |
| Pass 2 Domain | `pass2_domain` |
| Pass 2 Rationale | `pass2_rationale` |
| Pass 2 Recommendation | `pass2_recommendation` |
| EMD Amount (PDF) | `emd_amount` |
| Contract Value (PDF) | `contract_value` |
| Bid Status | `bid_status` |
| Extension Count | `extension_count` |

### bids_YYYY-MM-DD.xlsx (Sheet: Bids)
Full database snapshot. All columns. CLOSED rows hidden by default.

---

## PDF Storage Structure
```
downloads/
  Pursue/
    YYYY-MM-DD/
      {sanitized_tender_number}/     ← '/' in tender number → '_'
        RFQ_filename.pdf
        Annexure_1.pdf
        ...
  Pursue_with_Ramp_Up/
    YYYY-MM-DD/
      {sanitized_tender_number}/
  Assess_Further/
    YYYY-MM-DD/
      {sanitized_tender_number}/
  Decline/
    YYYY-MM-DD/
      {sanitized_tender_number}/
```
Folder assigned from pass 2 recommendation. Date subfolder added per run (matches GEM pattern).

---

## End-to-End Processing Pipeline

### Phase 1: Scrape (Playwright — see `02_portal_mechanics.md`)
```
python hal_tool.py run
```
1. Launch a persistent headless Chromium context (`.browser_profile/`).
2. `open_free_view`: goto `/HAL/` → click "Go to Tender Free View" (new tab).
3. `find_results_scope`: click Search → wait for `#myTable`.
4. Attach a context response listener that captures tender JSON
   (`jsonBusinessDatails` / `lmBusinessDatails`) from `Renderer`/`UiRenderer`
   network responses; also seed from the loaded first-window page.
5. Paginate by clicking `#scroll-right`; stop at `NO_OF_ROWS`, 4 stagnant
   scrolls, or when the scroll control disappears.
6. Progressively upsert each window's new records via `on_page` →
   `upsert_raw_tender` (NEW on first sight, ACTIVE/EXTENDED on re-fetch).
7. CLOSED sweep: `closing_date < TODAY` → `bid_status = CLOSED`.

> The pre-implementation design planned a plain-HTTP `requests.Session`
> "8-step enc/chkSum chain"; the shipped tool uses Playwright instead. The DB
> upsert/lifecycle logic below is unchanged.

### Phase 2: Pass 1 Scoring
Runs automatically after scrape in `hal_tool.py run`.

1. Query all tenders where pass1_score IS NULL and bid_status != CLOSED
2. Batch 25 at a time → Haiku with capability_reference.md system prompt + few-shot examples
3. Validate response (all IDs present, no identical consecutive rationales)
4. Write scores to DB; set run_pass2=1 if score >= 3
5. Export pass1_YYYY-MM-DD.xlsx (newly scored + EXTENDED tenders)
6. Mark pass1_exported=1 on exported tenders

### Phase 3: Human Review
Human opens pass1_YYYY-MM-DD.xlsx and edits:
- `Run Pass 2`: Y = force include, N = force exclude, blank = use auto-threshold
- `Human Override Score`: corrected score (any integer 0–5)
- `Human Override Reason`: explanation (feeds few-shot examples)

### Phase 4: Pass 2 Ingest
```
python hal_tool.py run-pass2 pass1_YYYY-MM-DD.xlsx
```
1. Read Excel → sync Run Pass 2 flag (Y→1, N→-1) to DB
2. Apply Human Override Score/Reason to DB
3. Human overrides feed feedback + few_shot_examples tables
4. Idempotency: excel_log tracks ingested filenames; re-ingestion is a no-op unless force=True

### Phase 5: Pass 2 Scoring
Runs after ingest in same `run-pass2` command.

Candidates: `run_pass2=1` OR (`pass1_score >= 3` AND `run_pass2 != -1`)
Excluded: `pass2_score IS NOT NULL`, `pass2_attempted=1`, `bid_status=CLOSED`

A single Playwright context and one shared search page are opened for the whole
Pass 2 run; the search page is reused (reloaded to the empty-form URL) between
tenders so the portal session stays warm.

Per tender (`scorer_pass2.score_tender_pass2`):
1. Mark `pass2_attempted=1` immediately (prevents retry on failure)
2. Reload the shared search page → fill tender number → click Search →
   `find_tender_row` → click the Actions gear → "Show tender documents" →
   collect `DownloadController` URLs from every frame
3. Download ALL PDFs via `context.request.get()`; skip filename-matched
   boilerplate docs (`is_boilerplate_document`) and HTML viewer responses
4. Extract text (pdfplumber) → strip boilerplate sections/phrases + CID artifacts
   (`extract_and_clean`)
5. Extract emd_amount and contract_value from cleaned text (regex)
6. Send cleaned text to Sonnet for deep analysis — or, if cleaned text
   < `PASS2_LOW_TEXT_CHARS` (500), send the raw PDFs as base64 document blocks
7. Parse the structured response; store pass2 scores + financial values to DB
8. Save PDFs to downloads/{recommendation}/{date}/{sanitized_tender_number}/
9. Export pass2_YYYY-MM-DD.xlsx

---

## Pass 2 Document Handling

### Download ALL documents, then filter:

**Skip entire document** if name matches known boilerplate:
- AS9100D Compliance
- Checklist
- Debar letter undertaking
- PBG Format
- Omnibus IP Format / Standalone IP Format
- Annexure II A and B (integrity pact)

**Keep and clean:**
- Request for Quotation (RFQ) — always primary
- Annexure 1, 2, 3, 4 (unless name matches boilerplate above)
- Scope of Work, Technical Specification, BOQ, Drawings
- Enclosure 1, Quality Requirements

**Within kept PDFs — strip before sending to Sonnet:**
- CID encoding artifacts (undecoded Devanagari / non-English glyphs)
- Standard T&C and compliance clauses
- Signature blocks and blank pages
- Page headers and footers

**Low text-yield PDF (< 500 chars after extraction):** Send as base64 native PDF to Sonnet instead of extracted text.

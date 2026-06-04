# GEM Implementation Patterns — Reference for HAL Tool

GEM source (read-only reference): `/Users/kartrama/Documents/Projects/AI/geminiTest/GEMAutomation/Implementation`

**Do NOT copy modules directly.** Rewrite from scratch for HAL, using these patterns as design blueprints. The HAL tool has different session handling, data shapes, and schema.

---

## Module Structure to Replicate

```
hal_tool.py               ← CLI entry point (run / run-pass2 / ingest-excel / export-excel / score-pending)
config.py                 ← BASE_DIR, DB_PATH, EXPORTS_DIR, DOWNLOADS_DIR, CAPABILITY_REF_PATH,
                             ANTHROPIC_API_KEY, PASS2_THRESHOLD=3
modules/
  session.py              ← HAL session handler (replaces csrf_handler.py — no CSRF for HAL)
  fetcher.py              ← scrape listings + download PDFs via enc chain
  scorer_pass1.py         ← Haiku batch scoring, validation gates, few-shot injection
  scorer_pass2.py         ← Sonnet deep analysis, PDF extraction, financial value parsing
  db.py                   ← all SQLite ops (connection per function, migrate pattern)
  excel_export.py         ← export_to_excel, export_pass1_delta, export_pass2_delta
  excel_ingest.py         ← read human edits from Excel → write to DB
  feedback.py             ← few-shot example management
```

---

## Session Handler — superseded by Playwright

> **What shipped.** The original plan (below) was a plain-HTTP `requests.Session`
> following an "enc/chkSum chain". The implemented `modules/session.py` uses
> **Playwright browser automation** instead — see `02_portal_mechanics.md`. GEM:
> CSRF token from cookie, sent in POST body. HAL: no token; a persistent headless
> Chromium context carries `JSESSIONID` automatically and generates the
> session-bound `enc`/`chkSum` tokens by navigating the real portal SPA.

Current session model:
- `config.chromium_launch_args()` + `pw.chromium.launch_persistent_context(
  user_data_dir=BROWSER_PROFILE_DIR, headless=True, accept_downloads=True,
  ignore_https_errors=True)` — one persistent profile (`.browser_profile/`) reused
  across runs so the session survives between scrape and Pass 2.
- `session.open_free_view` → `session.find_results_scope` reach the results table;
  `enc`/`chkSum` tokens are never constructed by hand or cached across runs.

~~Original plan (not implemented):~~
```python
# def get_session() -> requests.Session:  # NOT USED — replaced by Playwright
#     session = requests.Session()
#     session.get("https://eproc.hal-india.co.in/ROOTAPP/servlet/"
#                 "asl.tw.homepage.controller.HomePageAjaxController?DB_COMPANY=HAL")
#     return session
```

---

## Pass 1 Scoring Patterns

### Batch Size
25 bids per API call. Larger batches risk response collapse.

### API Call
```python
client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=8192,
    system=[{"type": "text", "text": capability_ref + few_shot_text,
             "cache_control": {"type": "ephemeral"}}],
    messages=[{"role": "user", "content": numbered_bid_list}],
)
```
Response format: JSON array `[{tender_number, line_number, score, confidence, domain, rationale}]`

### Validation Gates (before writing any result)
1. **All input IDs present** — if any missing, retry those bids individually
2. **No consecutive identical rationales** — indicates response collapse; retry flagged pairs individually

### Prompt Note for HAL
Input is richer than GEM (which only had a one-liner title). HAL pass 1 sends:
- Tender Description
- Region (HAL division)
- Buyer type (IMM / WORKS / OUTSOURCING)
- EMD (from listing)
- Estimated Cost
- Closing Date
- Bidder Type

Still use "generous leeway" note — short descriptions shouldn't be penalised.

### Few-Shot Injection
```python
examples_text = "\n\n---\n## Calibration examples from human feedback\n"
for ex in few_shots[:8]:
    examples_text += f'\nTender: "{ex["tender_title"]}"\nCorrect score: {ex["correct_score"]}\nReason: {ex["reason"]}\n'
system = capability_ref + examples_text
```

---

## Pass 2 Scoring Patterns

### Execution Order
1. `set_pass2_attempted(tender_number, line_number)` — called BEFORE download; prevents retry on failure
2. Reuse the shared Playwright search page → fill tender number → Search →
   find row → Actions gear → "Show tender documents" → collect download URLs →
   download each PDF via `context.request.get()`
3. Extract + clean text per PDF
4. Extract `emd_amount` and `contract_value` from cleaned text before LLM call
5. Combine cleaned texts from all kept documents
6. Call Sonnet

### Sonnet Call
```python
client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=600,
    system=[{"type": "text", "text": capability_ref,
             "cache_control": {"type": "ephemeral"}}],
    messages=[{"role": "user", "content": [
        {"type": "text", "text": f"Bid document:\n\n{combined_text}\n\n{strict_prompt}"}
    ]}],
)
```

For low text-yield PDFs (< 500 chars): send as base64 native PDF document block instead:
```python
{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
```

### Response Parsing
Parse the structured text output for: SCORE, CONFIDENCE, DOMAIN MATCH, MATCHING TECH, GAPS, RATIONALE, RECOMMENDATION.
Reuse `parse_score_response()` pattern from GEM's scorer_pass1.py, rename keys to `pass2_*`.

---

## Database Patterns

### Connection per Function
```python
def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
```
Open and close per operation. No persistent connection. Use context managers.

### Migration Pattern
```python
def _migrate():
    migrations = [
        "ALTER TABLE tenders ADD COLUMN new_col TEXT",
    ]
    with _get_conn() as conn:
        for sql in migrations:
            try:
                conn.execute(sql)
            except Exception:
                pass  # Column already exists
```

### Upsert — Preserve Human Fields
On re-fetch (upsert_raw_tender): never overwrite pass1_score, pass2_*, human_override_*, run_pass2, pass2_attempted, pass1_exported.
Update: buyer, description, estimated_cost, emd_listing, closing_date, last_seen_at.
Transition logic:
- First time seen → bid_status = NEW
- Re-fetched, closing_date unchanged, not CLOSED → ACTIVE
- Re-fetched, closing_date changed, not rejected → EXTENDED, extension_count++, save previous_closing_date

### run_pass2 Flag
- `0` = default (auto-threshold: pass1_score >= 3 → qualifies)
- `1` = human forced YES (always runs, regardless of score)
- `-1` = human forced NO (never runs, even if score >= 3)
- Rule: once set to 1, never auto-downgrade. Upgrade from -1 → 1 is allowed.

### pass2_attempted Flag
Monotone: once set to 1, stays 1. Prevents endless retry if PDF download or Sonnet call fails.

### pass1_exported Flag
Set to 1 after a tender is included in a pass1 delta export.
Cleared back to 0 when bid_status transitions to EXTENDED (deadline pushed = needs re-review).
`get_unexported_pass1_bid_numbers()` recovers any scored-but-not-yet-exported bids from prior runs.

---

## Excel Export Patterns

### Human Column Merge on Re-export
Before writing `bids_YYYY-MM-DD.xlsx`, read back the three human columns from the existing file:
- Run Pass 2
- Human Override Score
- Human Override Reason

Merge them into the new DataFrame so human edits are never lost when the file is regenerated after pass 2 scoring.

### CLOSED Row Hiding
Include CLOSED bids in the export but set `ws.row_dimensions[n].hidden = True`. They remain in the file for history but don't clutter the default view.

### Conditional Formatting (score-based colours)
- Pass 2 PURSUE / PURSUE WITH RAMP-UP → green fill (stops further formatting)
- Pass 2 rec present but non-PURSUE → no colour (stops P1 rules firing)
- Pass 1 score 5 → blue; 4 → yellow; 3 → orange

### Delta Export Append
If the delta file already exists (same-day second run), read it and concat + deduplicate on Tender Number before writing. Prevents wiping morning exports when afternoon scoring adds more rows.

---

## Excel Ingest Patterns

### Idempotency
`excel_log` table tracks ingested filenames. `is_excel_ingested(filename)` returns True if already done. `ingest_excel(path, force=True)` bypasses this for pass 2 ingest.

### Run Pass 2 Sync
```
Y  →  upsert_run_pass2_flag(tn, ln, 1)
N  →  upsert_run_pass2_flag(tn, ln, -1)
blank →  no change
```

### Feedback Loop
Every human override → `process_feedback()`:
1. Insert into `feedback` table
2. Insert into `few_shot_examples` table (for future Haiku calibration)
No auto-promotion to exclusion rules (HAL tool has no exclusion_rules table).

---

## Key HAL Differences from GEM

| Aspect | GEM | HAL |
|--------|-----|-----|
| Transport | `requests` HTTP | Playwright headless Chromium (persistent profile) |
| Session | CSRF token + cookie | `JSESSIONID` auto-issued; carried by browser |
| Data format | JSON API response | JSON captured from `Renderer` network responses |
| Primary key | `bid_number` (single) | `(tender_number, line_number)` composite |
| Navigation | Direct API URLs | SPA clicks + session-bound enc/chkSum tokens |
| Documents | 1 PDF per bid | Multiple PDFs per tender |
| PDF access | Session auth required | Public, no auth |
| Classification | ministry / org / dept | buyer / tender_region |
| Quantity | Present | Absent for most HAL tenders |
| Delta logic | Yes (24hr window) | No — full scrape every run |
| Exclusion rules | Yes | No |
| Financial extraction | emd_amount only | emd_amount + contract_value |

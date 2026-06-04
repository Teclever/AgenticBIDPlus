# HAL Bid Automation — Project Context

## Purpose

Monitors HAL India's e-procurement portal (https://eproc.hal-india.co.in), automatically discovers all open tenders, scores them against company capability using Claude AI, and generates daily Excel review files for human decision-making — identical in purpose to the existing GEM portal automation tool.

Company: Teclever. HAL is a primary client across multiple domains (Test Rigs, Avionics, Simulators). This tool automates daily tender monitoring and pre-screening so no relevant HAL bid is missed.

## Key Design Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Scrape strategy | Full scrape every run | ~145 total active tenders — delta logic adds complexity without benefit |
| Authentication | None required | Entire portal publicly accessible including PDF downloads |
| Pass 1 model | `claude-haiku-4-5-20251001` | Fast, cheap, batch 25 at a time |
| Pass 2 model | `claude-sonnet-4-6` | Strict deep document analysis |
| Pass 2 trigger | score ≥ 3 auto-qualifies; score < 3 only if human flags Y | Mirrors GEM tool logic |
| Pass 2 documents | Download ALL PDFs, strip boilerplate, send cleaned text | Option B — more complete than RFQ-only |
| Excel format | Daily pass1 + pass2 delta files, same structure as GEM | Consistent with existing workflow |
| PDF storage | `downloads/{recommendation}/{YYYY-MM-DD}/{tender_number}/` | Matches GEM pattern with date subfolder |
| Exclusion rules | Not implemented | Pass 1 score/recommendation is the gate |
| Feedback/few-shot | Yes — same as GEM | Human corrections feed future scoring |
| Schema | HAL-specific, not 1:1 GEM copy | HAL data structure differs significantly |

## Pass 1 Input Fields (sent to Haiku)
- Tender Description (from listing)
- Tender Region (HAL division)
- Buyer (IMM / WORKS / OUTSOURCING)
- EMD (from listing)
- Closing Date
- Bidder Type (Both / Indian / Foreign)
- Estimated Cost (from listing)

## Pass 2 Trigger Logic
- `run_pass2 = 1` → always run (human forced yes)
- `run_pass2 = -1` → never run (human forced no)
- `run_pass2 = 0` (default) → run if `pass1_score >= 3`
- Human rejection (override_score set ≤ 0) blocks even score ≥ 3

## PDF Financial Extraction (Pass 2)
- **`emd_amount`**: precise EMD from PDF (listing value often RS0/--NA--)
- **`contract_value`**: total project value from RFQ PDF — key for go/no-go judgment

## File Layout (planned)
```
HALAutomation/
  capability_reference.md     ← scoring system prompt (active tool component)
  references/                 ← GEM reference docs and sample Excel files
  context/                    ← this design context (all four files)
  data/                       ← runtime: bids.db, state.json (created at runtime)
  exports/                    ← runtime: pass1_*.xlsx, pass2_*.xlsx, bids_*.xlsx
  downloads/                  ← runtime: PDFs organised by recommendation
  modules/                    ← Python modules (created at implementation)
  hal_tool.py                 ← main entry point (created at implementation)
  config.py                   ← paths and settings (created at implementation)
```

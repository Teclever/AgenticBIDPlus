# HAL Bid Automation — Design Context Index

This folder contains the full design context for the HAL e-procurement portal bid automation tool.
Established through a structured requirements session on 2026-05-30.
Use these files to orient any agent or developer starting work on this project.

## Files

| File | Contents |
|------|----------|
| `01_project_context.md` | Goals, scope, and all key design decisions |
| `02_portal_mechanics.md` | Complete HTTP request chain, session handling, data structures |
| `03_schema_and_pipeline.md` | Database schema, Excel formats, PDF storage, end-to-end pipeline |
| `04_gem_implementation_patterns.md` | GEM source patterns to carry forward (models, batch logic, upsert, export) |

## Quick-Start Summary

- **Portal**: https://eproc.hal-india.co.in — publicly accessible, no login
- **Scrape transport**: Playwright headless Chromium (persistent profile) — the
  planned plain-HTTP "enc/chkSum chain" was abandoned; see `02_portal_mechanics.md`
- **Data**: Tenders captured as JSON (`jsonBusinessDatails` / `lmBusinessDatails`)
  from `Renderer` network responses — not HTML-table scraping
- **Pipeline**: Full scrape → Haiku pass 1 → human review Excel → Sonnet pass 2 → Excel
- **Models**: `claude-haiku-4-5-20251001` (pass 1), `claude-sonnet-4-6` (pass 2)
- **DB**: SQLite, primary key `(tender_number, line_number)`
- **GEM reference source**: `/Users/kartrama/Documents/Projects/AI/geminiTest/GEMAutomation/Implementation`
- **GEM reference docs**: `../references/` folder

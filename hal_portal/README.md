# HAL Bid Automation

Monitors the [HAL India e-procurement portal](https://eproc.hal-india.co.in), discovers all open tenders, scores them against Teclever's capabilities using Claude AI, and produces daily Excel review files.

## Overview

| Stage | What happens |
|-------|-------------|
| Scrape | Full portal sweep — all active tenders fetched every run |
| Pass 1 | Claude Haiku scores each tender 0–5 against `capability_reference.md` |
| Human review | Pass 1 Excel opened; reviewer marks Y/N on "Run Pass 2" column |
| Pass 2 | Claude Sonnet deep-reads all tender PDFs for shortlisted tenders |
| Output | Daily pass1, pass2, and full-snapshot Excel files |

## Repository Layout

```
HALAutomation/
  config.py                   ← paths, model names, thresholds
  hal_tool.py                 ← CLI entry point
  run_hal.sh                  ← runner wrapper (zsh) — runs the tool
  start.sh                    ← launcher — activates venv + opens Claude Code
  requirements.txt
  .env.example

  modules/
    session.py                ← Playwright portal navigation helpers
    fetcher.py                ← portal scrape: network-listener JSON capture + pagination
    scorer_pass1.py           ← Haiku batch scoring, validation gates
    scorer_pass2.py           ← Sonnet deep analysis + PDF extraction
    db.py                     ← SQLite operations
    excel_export.py           ← pass1 / pass2 / full-snapshot exports
    excel_ingest.py           ← read human edits back into DB
    feedback.py               ← few-shot example management

  context/                    ← design context (read-only reference)
    CONTEXT_INDEX.md
    01_project_context.md
    02_portal_mechanics.md
    03_schema_and_pipeline.md
    04_gem_implementation_patterns.md

  references/                 ← GEM reference docs and sample Excel files
  tests/test_live.py          ← live Playwright smoke tests

  data/
    capability_reference.md   ← scoring system prompt (source, tracked)
    bids.db                   ← runtime: SQLite store (gitignored)
  exports/                    ← runtime: pass1_*.xlsx, pass2_*.xlsx, bids_*.xlsx (gitignored)
  downloads/                  ← runtime: PDFs organised by recommendation (gitignored)
  .browser_profile/           ← runtime: persistent Playwright session (gitignored)
```

This folder is self-contained and portable: copying it to another machine and
running `pip install -r requirements.txt && playwright install chromium` is
enough to run it. When the multi-portal dashboard project lands (see the GeM
project's `dashboard_plans/`), this whole folder drops in as `portals/hal/`;
shared `core/` logic is owned by that project, not this one.

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/Teclever/HALAutomation.git
cd HALAutomation

# 2. Create virtual environment
python -m venv venv

# 3. Install dependencies
source venv/bin/activate
pip install -r requirements.txt

# 4. Set your API key
cp .env.example .env
# Edit .env and add: ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

```bash
# Daily run — scrape + pass 1 score + export
./run_hal.sh run

# After human review: ingest edits + run pass 2 + export
./run_hal.sh run-pass2 exports/pass1_2026-05-30.xlsx

# Score any unscored tenders without re-scraping
./run_hal.sh score-pending

# Ingest a reviewed Excel file into the DB
./run_hal.sh ingest-excel exports/pass1_2026-05-30.xlsx

# Regenerate today's full snapshot Excel
./run_hal.sh export-excel
```

`run_hal.sh` will prompt for `ANTHROPIC_API_KEY` interactively if not set in the environment.

To open a Claude Code session with the venv activated and the API key set, use:

```bash
./start.sh
```

## Pass 2 Trigger Logic

| `run_pass2` DB flag | Behaviour |
|---------------------|-----------|
| `0` (default) | Auto: runs if `pass1_score >= 3` |
| `1` (Excel: Y) | Force-include regardless of score |
| `-1` (Excel: N) | Force-exclude regardless of score |

## Output Files

| File | Contents |
|------|----------|
| `exports/pass1_YYYY-MM-DD.xlsx` | Newly scored tenders — human-editable Run Pass 2 / Override columns |
| `exports/pass2_YYYY-MM-DD.xlsx` | Pass 2 results — includes EMD Amount and Contract Value from PDFs |
| `exports/bids_YYYY-MM-DD.xlsx` | Full DB snapshot — all tenders, CLOSED rows hidden |

Downloaded PDFs are stored under `downloads/{Recommendation}/{YYYY-MM-DD}/{tender_number}/`.

## Design Context

Full design decisions, portal HTTP mechanics, database schema, and implementation patterns are documented in the [`context/`](context/CONTEXT_INDEX.md) folder.

## Portal Notes

- No login required — entire portal is publicly accessible
- Session token (`JSESSIONID`) is auto-issued on first request
- All navigation uses encrypted `enc` + `chkSum` tokens that are session-specific — the full 8-step chain must be followed per run
- Tender numbers contain `/` — sanitised to `_` for folder/filenames

## Models

| Stage | Model |
|-------|-------|
| Pass 1 | `claude-haiku-4-5-20251001` |
| Pass 2 | `claude-sonnet-4-6` |

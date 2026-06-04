# HAL_Portal — Front-End Handoff Pack

Reference materials for building the multi-portal front-end app's **HAL adapter**.
Copied out of the standalone HAL Bid Automation repo: documentation, a live sample
database, and the full scraper source (under `src/`) for reference. The
authoritative runnable copy stays in the original repo; treat `src/` here as
read-only reference for how the adapter works and what it exposes.

## Read in this order
1. **`ARCHITECTURE_FRONTEND.md`** — the integration spec. Start here. Consolidated
   DB model, the Pass-1 + vector-DB + on-demand-summary workflow, deltas from the
   standalone tool, and retention/cleanup rules.
2. **`context/02_portal_mechanics.md`** — how HAL is actually scraped (Playwright).
3. **`context/03_schema_and_pipeline.md`** — DB schema + Excel formats + pipeline.
4. **`context/04_gem_implementation_patterns.md`** — scoring/DB/export patterns.
5. **`context/01_project_context.md`**, **`context/CONTEXT_INDEX.md`** — design background.
6. **`README.md`** — standalone-tool overview (CLI commands, file layout).

## Files
| Path | What it is |
|------|------------|
| `ARCHITECTURE_FRONTEND.md` | Front-end integration architecture (primary) |
| `README.md` | Standalone HAL tool overview |
| `context/*.md` | Design context (portal mechanics, schema, pipeline, patterns) |
| `data/capability_reference.md` | Pass-1/Pass-2 scoring system prompt |
| `data/bids.db` | **Live sample SQLite** — 143 tenders, all Pass-1 scored, no Pass-2 |
| `src/` | Full scraper source (reference only — see below) |

## Source code (`src/`) — reusable adapter pieces
Read these to see exactly what the front end can call/import. Mapping to the
integration surface in `ARCHITECTURE_FRONTEND.md` §4:

| File | Role | Front-end relevance |
|------|------|---------------------|
| `src/hal_tool.py` | CLI entry (`run`, `run-pass2`, `score-pending`, …) | Subprocess option; shows pipeline orchestration |
| `src/config.py` | Paths, model names, thresholds, Chromium launch args | Tunables (PASS2_THRESHOLD=3, model IDs) |
| `src/modules/fetcher.py` | Playwright scrape + document download | `fetch_all_tenders`, `open_tender_documents`, `download_document` |
| `src/modules/session.py` | Portal navigation helpers (Playwright) | `open_free_view`, `find_results_scope`, `fill_tender_number` |
| `src/modules/scorer_pass1.py` | Haiku batch scoring + validation gates | `score_bids_pass1_bulk` |
| `src/modules/scorer_pass2.py` | Sonnet deep-scoring + PDF extract/clean | `extract_and_clean` (reuse for vector-DB chunking) |
| `src/modules/db.py` | SQLite schema + all DB ops | Schema of `data/bids.db`; lifecycle/upsert logic |
| `src/modules/excel_export.py` / `excel_ingest.py` | Excel I/O | Column maps; **not needed** if front end skips Excel |
| `src/modules/feedback.py` | Few-shot example management | Calibration loop reference |
| `src/requirements.txt` | Python deps (anthropic, pdfplumber, playwright, …) | Runtime deps for the adapter |
| `src/run_hal.sh` | External runner wrapper (zsh) — `run` / `run-pass2` / `score-pending` / … | How the tool is invoked from a terminal; subprocess option |
| `src/start.sh` | Launcher — activates venv, sets `ANTHROPIC_API_KEY`, opens Claude Code | Local dev setup reference |
| `src/.env.example` | Env template (`ANTHROPIC_API_KEY=`) | Copy to `.env` and fill to run the adapter |
| `src/tests/test_live.py` | Live Playwright smoke test | Example of driving the scraper end-to-end |

> The single-bid, no-Sonnet document fetch the front end needs (see
> `ARCHITECTURE_FRONTEND.md` §5) does not exist as one function yet — it composes
> from `fetcher.open_tender_documents` + `download_document` +
> `scorer_pass2.extract_and_clean`.

## The database (`data/bids.db`)
Real scraped snapshot to model the consolidated table against. Key facts:
- One table `tenders`, composite PK **`(tender_number, line_number)`** — this is
  the HAL `source_pk` the front end joins on.
- Listing fields populated (buyer, region, description, estimated_cost,
  emd_listing, closing_date, bidder_type) + Pass-1 scoring
  (`pass1_score`/`confidence`/`domain`/`rationale`/`gaps`).
- Lifecycle: `bid_status` = NEW / ACTIVE / EXTENDED / CLOSED.
- Control flags: `run_pass2` (0 auto / 1 force-yes / -1 force-no),
  `pass2_attempted`, `pass1_exported`.
- Richer columns exist in the schema but are **empty** in the current scraper
  (tender_cover, contact_*, qualification_criteria, etc.) — see the "unused
  schema columns" note in `context/02_portal_mechanics.md`.
- Inspect: `sqlite3 data/bids.db ".schema tenders"` and
  `sqlite3 data/bids.db "SELECT tender_number,line_number,pass1_score,bid_status FROM tenders LIMIT 10;"`

Snapshot taken 2026-06-02. It is a point-in-time copy; the source repo's DB keeps
evolving independently.

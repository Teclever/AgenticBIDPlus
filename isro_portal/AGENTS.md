# AGENTS.md — orientation for automated agents

Read this first, then [`README.md`](README.md) for full detail. This file is the
fast path to understanding, maintaining, and safely extending the project.

## What this is

A standalone CLI that scrapes the ISRO e-procurement portal, scores tenders with
the Anthropic API in two passes, and uses Excel as a human review surface. SQLite
(`data/bids.db`) is the single source of truth.

## Where to make a change

| Want to change… | Edit this file |
|------------------|----------------|
| Portal HTML parsing, URLs, scraping | [`modules/fetcher.py`](modules/fetcher.py) |
| DB schema, lifecycle, Pass 2 candidate rule | [`modules/db.py`](modules/db.py) |
| Pass 1 prompt, batch size, JSON parsing | [`modules/scorer_pass1.py`](modules/scorer_pass1.py) |
| Pass 2 prompt, doc download, extraction | [`modules/scorer_pass2.py`](modules/scorer_pass2.py) |
| Excel columns, colours, conditional rules | [`modules/excel_export.py`](modules/excel_export.py) |
| How human edits are read back | [`modules/excel_ingest.py`](modules/excel_ingest.py) |
| Phase order, CLI commands, logging | [`isro_tool.py`](isro_tool.py) |
| Paths, model names, thresholds | [`config.py`](config.py) |
| Scoring rubric (no code) | [`data/capability_reference.md`](data/capability_reference.md) |

## Control flow

`isro_tool.py:main()` routes a command → a `cmd_*` function that calls modules in
order. All scoring goes through `scorer_pass1` / `scorer_pass2`; all persistence
goes through `db`. No module talks to the portal except `fetcher`.

## Invariants — do not break

- **DB is master.** Daily `run` must not auto-ingest Excel.
- **Always UPSERT by `tender_id`.** Never blind-insert; never overwrite scores or
  human columns (`run_pass2`, `human_override_score`, `human_override_reason`) on
  a re-scrape.
- **`pass2_attempted` is set before Pass 2 work** and is monotonic (prevents retry
  loops on flaky downloads/API).
- **`CLOSED` is terminal.** Never reopen a closed tender.
- **Pass 1 only scores `pass1_score IS NULL`.** Re-fetched bids are not re-scored.
- **`pass1_exported` gates the pass1 delta** so a bid appears in exactly one
  `pass1_*` delta file.
- **Never hardcode `ANTHROPIC_API_KEY`** — it is read from the environment.

## Pass 2 candidate rule (source: `db.py:query_pass2_candidates`)

Include when not CLOSED, not yet scored, not attempted, AND
(`run_pass2 = 1`) OR (`pass1_score >= PASS2_THRESHOLD` AND `run_pass2 != -1`).
`PASS2_THRESHOLD = 3`. Excel maps `Y → 1`, `N → -1`, blank → `0`.

## How to verify a change quickly

```bash
python3 -m compileall config.py isro_tool.py modules/   # syntax
./run.sh export-excel                                    # no-API smoke test
./run.sh score-pending                                   # Pass 1 path (needs key)
```

Inspect state directly with SQLite when needed:

```bash
.venv/bin/python - <<'PY'
import sqlite3
c = sqlite3.connect("data/bids.db"); c.row_factory = sqlite3.Row
print("total", c.execute("select count(*) from bids").fetchone()[0])
print("scored", c.execute("select count(*) from bids where pass1_score is not null").fetchone()[0])
PY
```

## Runtime artifacts (gitignored)

`data/bids.db`, `exports/*.xlsx`, `downloads/`, `.venv/`, `.env`. Do not commit
these. Source of portal structure reference: `ISRO E Procurement.txt`.

## Current gaps (safe to pick up)

1. Pass 2 JSON parsing is less robust than Pass 1's `_extract_json`.
2. No reconciliation for tenders that vanish from the listing (only date-based
   CLOSED sweep exists).

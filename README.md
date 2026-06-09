# Teclever BidPlus

AI-powered bid intelligence platform for HAL, ISRO, and GeM government procurement portals.

## What it does

- Scrapes bids nightly from three portals (HAL via Playwright, ISRO and GeM via HTTP)
- Filters irrelevant bids through a two-pass keyword eliminator before any AI call
- Scores every bid 1–5 with Claude Haiku (Pass 1)
- Detects Single Tender bids from document text; auto-rejects non-Teclever, promotes Teclever to score 5
- Generates structured AI summaries for high-scoring bids with Claude Sonnet (Pass 2)
- Serves a web UI for reviewing, accepting, and rejecting bids with inline Accept/Reject and next-bid navigation

## Architecture

```
bidplus/          Python backend package
  adapters/       Portal scrapers (HAL, ISRO, GeM)
  web/            FastAPI web server + REST API
  data/           Scoring rubric + eliminator keyword lists
  scripts/        Setup and runtime helpers
frontend/         React + Vite + Tailwind web UI
deploy/systemd/   systemd units for the nightly timer and web server
```

**Runtime layout** (on the deploy host):

```
$BIDPLUS_RUNTIME_DIR/
  .env               ANTHROPIC_API_KEY
  parent.db          Central SQLite DB (all portals merged)
  hal/bids.db        HAL tool DB
  isro/bids.db       ISRO tool DB
  gem/bids.db        GeM tool DB
  hal/.browser_profile/   Playwright session (HAL login)
  logs/              Per-run portal logs
```

## Setup (first time)

```bash
export BIDPLUS_RUNTIME_DIR=~/bidplus-runtime
bash bidplus/scripts/setup_runtime.sh
cp .env.example ~/bidplus-runtime/.env
# edit .env and add your ANTHROPIC_API_KEY
```

## Running

**Web server** (production):

```bash
export BIDPLUS_RUNTIME_DIR=~/bidplus-runtime
~/bidplus-runtime/venv/bin/uvicorn bidplus.web.app:app --host 0.0.0.0 --port 8000
```

Or use the convenience script (builds the frontend if needed):

```bash
bash bidplus/scripts/run_web.sh
```

**Frontend dev server** (hot reload against the FastAPI backend):

```bash
cd frontend
npm install
npm run dev          # proxies /api → localhost:8000
```

**Nightly pipeline** (manual trigger):

```bash
~/bidplus-runtime/venv/bin/python -m bidplus.launcher run
```

**User management**:

```bash
~/bidplus-runtime/venv/bin/python -m bidplus.users add name@teclever.com
~/bidplus-runtime/venv/bin/python -m bidplus.users list
```

## Key commands

| Command | Description |
|---------|-------------|
| `launcher run` | Full nightly cycle: scrape → score → merge → summarise → sweep |
| `launcher score <portal>` | Re-run Pass 1 (eliminator + Haiku) for unscored bids |
| `launcher summarize <portal> <pk>` | On-demand Pass 2 summary for one bid |
| `launcher sweep` | Lifecycle sweep only (mark CLOSED, retention, orphan reap) |
| `launcher run-status` | Check if a cycle is running; print active alerts |
| `launcher merge` | Merge tool DBs into parent.db |
| `launcher singletender-backfill` | Scan existing .txt files for Single Tender field; update DB (no downloads) |
| `launcher governance-delta` | Generate AI keyword governance proposals |

## Scoring

- **Score 0** — eliminated by keyword filter before Haiku (`pass1_method='keyword'`)
- **Score 1–3** — below threshold; shown but not auto-summarised. Single Tender detected on manual "Generate Summary".
- **Score 4** — local document extraction (no Sonnet). Single Tender detected; Teclever/masked upgraded to score 5.
- **Score 5** — full Sonnet summary generated overnight. Single Tender detected during Pass 2.

### Single Tender rules

Detected from `Single Tender Applicable: Yes` + `List of Seller Organization for participation` in the bid PDF.

| Org | Action |
|-----|--------|
| Teclever (any case/spacing) | `pass1_score = 5` → Sonnet summary auto-runs |
| Masked / unreadable (`***`) | `pass1_score = 5` → Sonnet summary auto-runs |
| Readable, not Teclever | `auto_rejected = 1`, `user_state = 'rejected'` |

## Documentation

| File | Purpose |
|------|---------|
| `AGENTS.md` | Build rules, slice status, operative instructions for agents |
| `HANDOFF.md` | Current state brief for all slices |
| `frontend/HANDOFF.md` | Frontend-specific state, known issues, run instructions |
| `DEPLOY_WORKFLOW.md` | Deploy box provisioning checklist |
| `webapp-design/API.md` | Full REST API contract |
| `webapp-design/WEBAPP_DESIGN.md` | UX behaviour spec |

# Teclever BidPlus

AI-powered bid intelligence platform for HAL (e-Procurement + Corporate Tenders), ISRO, and GeM government procurement portals.

## What it does

- Scrapes bids nightly from **four** portals: HAL e-Procurement (`hal`, Playwright), HAL Corporate Tenders (`halc`, WordPress REST), ISRO and GeM (HTTP)
- Filters irrelevant bids through a two-pass keyword eliminator before any AI call
- Scores every bid 1–5 with Claude Haiku (Pass 1)
- Detects **Single AND Limited Tender** bids from document text; auto-rejects when restricted to a named non-Teclever list, promotes Teclever-listed to score 5, and surfaces masked/undisclosed lists for human review (flagged, never auto-accepted)
- Generates structured AI summaries for high-scoring bids with Claude Sonnet (Pass 2)
- Serves a web UI for reviewing, accepting, rejecting, and **resetting** bids with inline actions and next-bid navigation
- Exposes a **Google-Sheet remote control plane** (`bidplus-control` service) for off-site run status + triggering `run`/`rerun` on the outbound-only box (see `bidplus/control/README.md`)

## Architecture

```
bidplus/          Python backend package
  adapters/       Portal scrapers (HAL, HALC, ISRO, GeM)
  control/        Google-Sheet remote control-plane agent (bidplus-control)
  web/            FastAPI web server + REST API
  data/           Scoring rubric + eliminator keyword lists
  scripts/        Setup and runtime helpers
frontend/         React + Vite + Tailwind web UI
deploy/           systemd units (nightly timer, web server, control-plane agent)
```

**Runtime layout** (on the deploy host):

```
$BIDPLUS_RUNTIME_DIR/
  .env               ANTHROPIC_API_KEY
  parent.db          Central SQLite DB (all portals merged)
  hal/bids.db        HAL e-Procurement tool DB
  halc/bids.db       HAL Corporate Tenders tool DB
  isro/bids.db       ISRO tool DB
  gem/bids.db        GeM tool DB
  hal/.browser_profile/   Playwright session (HAL login)
  control/           Control-plane state + command logs
  control.env        bidplus-control config (BIDPLUS_CONTROL_SHEET_ID, …)
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
| `launcher run` | Full nightly cycle (all portals): scrape → score → merge → summarise → sweep |
| `launcher run --only <portal>` | Same cycle scoped to one portal (the control-plane `rerun`) |
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
- **Score 4** — local document extraction (no Sonnet). Single Tender detected; Teclever/masked upgraded to score 5. Also the **floor** for rescued AMC/CMC bids (see below).
- **Score 5** — full Sonnet summary generated overnight. Single Tender detected during Pass 2. **Auto-promote (boost) keywords** (`test rig`, `ATE`, `AI`, `signal conditioner`…) bypass the eliminator and force score 5.

### AMC/CMC maintenance contracts

Annual/Comprehensive Maintenance Contracts (AMC/CMC) normally trip the keyword eliminator. They are **rescued to Haiku Pass-1** instead of being auto-dropped when:

- the buyer is a **Level-1 organization** — HAL, ADA, ADE (incl. "Office of DG (Aero)"), ISRO + centres, BEL, CVRDE, CMTI, IIAP, wider DRDO (the HAL / HAL-C / ISRO portals are wholly Level-1) — **regardless of item**; **or**
- the buyer is any other org **and** the item is **not** facilities/IT infrastructure (CCTV, fire, chillers, UPS, EPABX, biometric, lifts, servers, storage, photocopier…).

Any rescued AMC/CMC bid is **floored to score 4 unless Haiku rates it 5**, so it always reaches human review (the score-4 queue). Infrastructure AMCs from non-Level-1 orgs stay filtered. The boost list takes precedence (forces score 5). Implemented in `bidplus/eliminator.py` (`amc_floor_qualifies`) + `scoring.score_portal`.

### Single / Limited Tender rules

Detected from `Single Tender Applicable: Yes` **or** `Limited Tender Applicable: Yes`, plus the `List of Seller Organization for participation` field in the bid PDF. Detection runs on the **raw** PDF text (the cleaned sidecar strips the table section where GeM puts these fields).

| Seller list | Action |
|-----|--------|
| Teclever (any case/spacing) | `pass1_score = 5` → Sonnet summary auto-runs |
| Masked / undisclosed (`***`) | `pass1_score = 5` + `is_single_tender=1` → surfaced for human review (never auto-accepted; appears in the dashboard "Single / Limited Tender" list) |
| Readable, not Teclever | `auto_rejected = 1`, `user_state = 'rejected'` |

## Documentation

| File | Purpose |
|------|---------|
| `AGENTS.md` | Build rules, slice status, operative instructions for agents |
| `HANDOFF.md` | Current state brief for all slices (see §17 for 2026-06-18/19 changes) |
| `bidplus/control/README.md` | Google-Sheet remote control plane: env, command vocab, deploy |
| `frontend/HANDOFF.md` | Frontend-specific state, known issues, run instructions |
| `DEPLOY_WORKFLOW.md` | Deploy box provisioning checklist |
| `webapp-design/API.md` | Full REST API contract |
| `webapp-design/WEBAPP_DESIGN.md` | UX behaviour spec |

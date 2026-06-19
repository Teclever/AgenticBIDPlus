# Teclever Bid Portal — Development Handoff

**As of:** 2026-06-09  
**Repo:** `BidAnalysisPortal/` (git root)  
**Authoritative rules:** [`AGENTS.md`](AGENTS.md) · full design [`MASTER_ACTION_PLAN_V3.md`](MASTER_ACTION_PLAN_V3.md) · deploy [`DEPLOY_WORKFLOW.md`](DEPLOY_WORKFLOW.md)

This file is the **current-state brief** for anyone continuing the build — human, Cursor,
Claude Code, Codex CLI, or any other tool. Read it **after** [`AGENTS.md`](AGENTS.md).
It does **not** depend on chat history or transcript IDs; §3–11 are self-contained.

---

## 1. What we are building

A **backend orchestrator** (`bidplus/`) that:

1. Runs three **modified** portal tools sequentially: **HAL → ISRO → GeM** (Playwright for HAL; HTTP for ISRO/GeM).
2. Each tool keeps its own **`bids.db`** under `$BIDPLUS_RUNTIME_DIR/<portal>/`.
3. **Pass 1** (Claude Haiku) scores every bid against **one** rubric file.
4. Later slices merge into **`parent.db`**, fetch documents, run a **single Sonnet summarization module** (score-gated), nightly retention, systemd timer.

The **web app** and **vector DB / local OCR** are explicitly out of scope for S0–S7. There is **no Excel workflow** in the orchestrator path (see §6).

---

## 2. Work completed (by slice — no chat links)

Use this section for *what was built*, not for opening old conversations. Slice
status and validation detail are in **§3**.

| Slice | What landed in the repo |
|-------|-------------------------|
| **S0** | `bidplus/` scaffold, `pyproject.toml`, runtime/iCloud guard, tool `config.py` relocation, `setup_runtime.sh`, `PortalAdapter` stub |
| **S1** | `bidplus/adapters/hal.py`, `hal_tool.py` `scrape-score` + `explain`, HAL Pass-1 full shape (`matching_tech`, `recommendation`), launcher HAL path; **live HAL run** validated |
| **S2** | `bidplus/adapters/isro.py`, `gem.py`, ISRO Pass-1 full shape + DB columns, `scrape-score` / `explain` on ISRO and GeM, launcher `run` over all `PORTALS`; **live 3-portal run validated** (2026-06-04→05) — HAL 139/136, ISRO 155/154, GeM 11,333/10,807 Pass-1-scored. **S2 closed.** |
| **Post-S2** | Single rubric at `bidplus/data/capability_reference.md`; per-portal rubric copies removed; all tools use `capability_reference_path()` |
| **S3** | `bidplus/merge.py` (gap-aware upsert, overlay-preserving, conditional/idempotent update, additive schema migration) + launcher `merge [portals…] [--check]`; `parent.db` created (WAL) with `{hal,isro,gem}_bids` + `users`/`scrape_runs`/`system_alerts`; **live-validated** against all 3 tool DBs |
| **S4** | `bidplus/runs.py` (scrape_runs in-progress→final rows, aggregate counts, sticky `system_alerts`, `active_run`/`active_alerts`) + `bidplus/gate.py` (tiered gate, NULL-safe exclusions) + launcher `run` rewritten as the full cycle (scrape → merge → gate, run-logging + isolation) and new `gate` / `run-status` commands; `deploy/systemd/bidplus.{service,timer}`; **validated** (17 checks) |
| **Docs** | `MASTER_ACTION_PLAN_V3.md` + `AGENTS.md` aligned on one unified rubric file |

**User decisions (carry forward):**

- Portal tools (`gem_portal/`, `hal_portal/`, `isro_portal/`) **will be changed** for orchestration; only **transport** (`fetcher.py`, HAL `session.py`, GeM `csrf_handler.py`) must not be reimplemented.
- **One physical rubric file** (not three copies) — implemented post-S2 at `bidplus/data/capability_reference.md`.
- **Rubric + grading + extraction/summarization** in one common place (`bidplus/`): **Pass-1 grading + eliminator → S5**, **Pass-2 summarization → S6**; only the rubric file is consolidated so far.
- Initial commit was done **externally** by the user; further agent work is largely **uncommitted** (see §8).
- **Scoring redesign (2026-06-04, plan §2 #9/#31/#32):** scoring moves **out of the tools** into a **shared module** (`bidplus/`, Decision #9‑A normalized-record seam); tools become **thin** (fetch + store + CLOSED/EXTENSION). **Pass 1** = title scoring 0–5; **Pass 2** = docs→summary (the legacy second-*scoring* Pass 2 is **deleted**). A **pre-Pass-1 eliminator** keyword gate is built (`bidplus/data/eliminator_keywords.json` + `bidplus/scripts/mine_eliminators.py`, protect≥3, **soft-flag** — see `WEBAPP_HANDOFF.md`). **Excel ingest/export + GeM exclusion pre-filter removed.** Slices renumbered **S0–S7** (new **S5** = scoring module + eliminator; **S6** = Pass 2; **S7** = lifecycle).
- **Eliminator design frozen (2026-06-05, `ELIMINATOR_DESIGN.md` — authoritative, supersedes older eliminator wording):** the gate is now **two-pass** (`eliminate = neg_hit AND NOT pos_hit`) — a high-precision **positive in-scope list** (`bidplus/data/inscope_signals.json`, 207 phrases + 30 tokens) vetoes elimination. The live lists are **DB rows** (`eliminator_terms`), seeded once from the JSON at first deploy, then changed only through a **governance loop** — runtime ledger (`eliminator_keyword_stats`) → periodic AI **delta** (ADD/REMOVE/REFINE) → `list_change_proposals` staging → **Excel review on the deploy box** (`$BIDPLUS_RUNTIME_DIR/list_review/{pending,ready,consumed}/`) → transactional apply at run start. A **promote** feeds the ledger (high-support term → strengthen the positive list, **not** auto-quarantine). New per-bid cols `auto_rejected`/`human_disposition`/`human_reason` + three governance tables (plan §7). Propagated into plan §32/§6 S5/§7, `AGENTS.md`, `WEBAPP_HANDOFF.md`, `DEPLOY_WORKFLOW.md`.

---

## 3. Build slices — status

| Slice | Goal | Code status | DONE-WHEN / validation |
|-------|------|-------------|-------------------------|
| **S0** Scaffold | `bidplus/` package, runtime dir, iCloud guard, merged deps, tool `config.py` relocation, `PortalAdapter` stub, Playwright check script | **Done** in tree | Validated in S0 session: venv under `~/bidplus-runtime`, Chromium headless, tool DB paths relocate, guard rejects iCloud paths |
| **S1** HAL orchestrator | `HALAdapter`, `hal_tool scrape-score` + `explain`, Pass-1 full shape (`matching_tech`, `recommendation`), minimal launcher | **Done** in tree | **Live:** 137 tenders scraped, 132 Pass-1 scored, `explain` OK; log `~/bidplus-runtime/logs/hal_20260604_143849.log` |
| **S2** ISRO + GeM | ISRO/GeM adapters, unified rubric content for ISRO, ISRO parser full shape, sequential launcher `run` | **Done + live-validated** | **Live (2026-06-04→05):** sequential HAL→ISRO→GeM, three populated `bids.db`, Pass-1 parses under unified rubric, `explain` per portal. HAL 139/136, ISRO 155/154, GeM 11,333/**10,807** scored. **526 GeM bids unscored** = ~23 transient `APIConnectionError` batches the in-tool scorer skipped to NULL (benign + recoverable; robustness fix held for **S5**). GeM was driven **standalone** (`gem_tool.py scrape-score`) after the launcher run took a `KeyboardInterrupt` at the GeM stage — data + scores identical, but the single-orchestrated-run path wasn't shown end-to-end. **Accepted as S2-complete.** |
| **S3** Parent merge | `parent.db`, gap-aware upsert, overlay preservation | **Done + validated (2026-06-05)** | `bidplus/merge.py` + launcher `merge [--check]`. **Live-validated:** parent mirrors all 3 tools (HAL 139 / ISRO 155 / GeM 11,333, 0 mismatches); 2nd merge idempotent (0 ins/0 upd); overlay (`user_state`/`docs_summarized`/`summary_json`) survives re-merge; EXTENDED updates only `bid_status`/`extension_count`/closing-date, overlay untouched; manual tool-row picked up next merge. WAL on. |
| **S4** Hardening | `scrape_runs`, sticky alerts, systemd timer, tiered queues | **Done + validated (2026-06-05)** | `runs.py` + `gate.py` + launcher cycle/`gate`/`run-status` + systemd units. **Validated (17 checks):** in-progress overall row (`finished_at IS NULL`) then finalized; 1 overall + 3 per-tool rows w/ counts + stage timings; failed portal → `failed` for it, **`partial`** overall, others finish; partial/failed raises **sticky** `system_alerts` (a later success leaves it active); all-failed → `failed`; tiered gate buckets 5/4/≤3 (auto5=23, local4=168) with **CLOSED + keyword excluded** (NULL-safe), matched to manual SQL. **Timer firing** = deploy-box (systemd) verification, units shipped. `deploy/systemd/bidplus-web.service` added 2026-06-08 for the FastAPI server. |
| **S5** Shared scoring module + eliminator | centralize Pass-1 out of the tools; normalized-record seam; **two-pass** eliminator gate (`neg & !pos`, read from `eliminator_terms` DB) shadow→hard; ledger + AI-delta + Excel governance; output-budget batching; 1:1 mapping; transient-error retry | **Done — all 3 chunks (2026-06-05).** ✅ C1 eliminator core (`bidplus/eliminator.py`: schema + idempotent seed + two-pass gate byte-faithful to the miner + shadow analysis; `scoring_records()` seam on all 3 adapters). ✅ C2 Haiku engine (`bidplus/scoring.py`: 1:1 mapping, per-item retry, transient retry/no-skip-to-NULL, no dup-gate). ✅ **C3 governance + cutover:** `bidplus/governance.py` — ledger (promote→`false_positives`++/requeue, accept/clear-table→`confirmed_rejections`++, **never auto-quarantine high-support**); AI delta ADD/REMOVE/REFINE + **keep-guard** (blocks neg-add hitting any score≥3 bid / removing an `under_review` term) → `list_change_proposals` → risk-coded **Excel** in `list_review/{pending,ready,consumed}/`; transactional `ready/`→apply at run start. **In-tool Pass-1 + GeM exclusion pre-filter removed** (3 tools scrape-only). `launcher run` rewired: governance-ingest → scrape → **centralized hard score** → merge → gate. **Hard cutover flipped** (`score_portal`/CLI default `mode='hard'`; `--shadow` retained); promoted bids bypass the eliminator. **Collision review resolved:** of 109 score≥3 collisions the operator rescued 4 via positive adds (`testing rig`/`test stand`/`shop floor`+`digitization`/`hlnm`) + removed neg unigram `blade` (kept `wiper blade`); other ~101 accepted. Governance loop validated end-to-end (deterministic, no-API: accept/promote/ledger, keep-guard block, Excel export, ready→apply→consumed). ✅ **Live 30-bid/portal hard smoke (2026-06-05):** HAL 25 model + 5 keyword, ISRO 28 + 2, GeM 5 + 25 — **0 unscored, 0 bad-provenance rows** (keyword rows carry `auto_rejected=1`+`pass1_eliminated_by`+score 0; model rows carry a score). Smoke caught + fixed a **composite-PK 1:1 mapping bug**: HAL `tender\|line` ids collided with the prompt's `\|` field separator (model echoed only the pre-`\|` part → 14/25 HAL survivors NULL); Pass-1 now maps by **line NUMBER** (digit-extracted), robust to any PK. | — |
| **S6** Pass 2: docs → summary | `fetch_documents`, local extract, **one** Sonnet summarization path | **In progress — built in 3 CHANNELS (2026-06-05).** ✅ **Ch1 Document Fetch** (committed `cc73a2c`): `fetch_documents` on all 3 adapters via a `fetch-docs <pk> --out <dir>` subcommand reusing each tool's transport (HAL Playwright enumerate-all + filename exclusion; ISRO single doc, HTML dropped; GeM primary + ranked spec links, 3-doc cap REMOVED, content-dedup). Live-validated. ✅ **Ch2 Local Extraction** (committed `73b58ae`): `bidplus/extraction.py` → relevant English text only (drop non-English + governance/T&C boilerplate; keep technical/financial crux), text→`.txt` in the bid folder, scans/images kept whole for Sonnet, regex local_fields (EMD/PBG/value/dates from RAW). Formats: PDF/Word/Excel/PPT/images native + legacy .doc/.xls/.ppt via LibreOffice (deploy needs `apt install libreoffice`). ✅ **Ch3 Sonnet Summarization** (`bidplus/summarize.py`) — **BUILT + REAL-SONNET VALIDATED (2026-06-05), UNCOMMITTED.** §8b module + score-gated wiring into `launcher run` (per-portal Pass-2: score-5 Sonnet, score-4 local extract), `summarize` CLI, `scrape_runs` counts, unreadable-doc (`unparsed_documents`) surfacing. LibreOffice intentionally NOT installed. Remaining: full integrated `run` on real data (deploy proof) + commit. See §13. | — |
| **S7** Lifecycle | CLOSED sweep, 7-day file retention, orphan reaping, overnight budget | **BUILT + dev-validated (UNCOMMITTED), 2026-06-06.** `bidplus/lifecycle.py` (+ `sweep` CLI; wired into `run` after the gate). `closed_sweep` (parse per-portal closing date → mark CLOSED, retain row+overlay, delete files), `retention_sweep` (N-day file age-out + empty-dir removal), `reap_orphans` (dirs with no parent row), `budget_report` (finished_at vs `OVERNIGHT_DEADLINE`). All four proven on synthetic data. Remaining: real full-cycle budget timing on the deploy box. | — |

**S2 + S3 + S4 + S5 DONE-WHEN: satisfied (2026-06-05). S6 (Pass 2) + S7 (lifecycle/retention) BUILT + dev-validated (S6 real-Sonnet, S7 synthetic). S6 committed `a66d62a`; S7 committed `2b9b8f9`. The remaining gate for BOTH is a real full-cycle `launcher run` on the deploy box (real scrape across 3 portals → Pass 1 → merge → Pass 2 Sonnet → sweep → budget-within-9am) — that's the deploy-phase proof, see §13/§14.** *(S2 caveat retained: GeM finished standalone after a mid-run interrupt; substance met. S4 timer firing is the one item deferred to deploy-box systemd verification. S5: hard cutover is live; full integrated nightly `run` is the deploy-box proof.)*

---

## 4. Repository layout (orchestrator)

```
bidplus/
  __init__.py
  config.py              # PARENT_DB_PATH, model pins, PORTALS, score gates (no parent.db use yet)
  runtime.py             # BIDPLUS_RUNTIME_DIR, iCloud guard, capability_reference_path()
  launcher.py            # run (HAL→ISRO→GeM), explain per portal
  data/
    capability_reference.md   # SINGLE canonical Pass-1 rubric (md5 ee7ab78026d5996e1d8f1edd22b11d72)
  adapters/
    base.py                # PortalAdapter, RunResult, FetchedDoc
    hal.py, isro.py, gem.py  # subprocess wrappers
  scripts/
    setup_runtime.sh       # venv + editable install + Playwright Chromium + seed .env
    check_chromium.py
pyproject.toml             # bidplus package; certifi==2026.4.22 pinned for GeM TLS
.env.example               # template → copy to $BIDPLUS_RUNTIME_DIR/.env
```

**Portal tools (modified, not replaced):**

| Portal | Entry | Orchestrator CLI | PK for `explain` |
|--------|-------|------------------|------------------|
| HAL | `hal_portal/src/hal_tool.py` | `scrape-score`, `explain <tn> <ln>` | `tender_number` + `line_number` |
| ISRO | `isro_portal/isro_tool.py` | `scrape-score`, `explain <tender_id>` | `tender_id` |
| GeM | `gem_portal/gem_tool.py` | `scrape-score`, `explain <bid_number>` | `bid_number` |

**Architecture choice:** adapters use **subprocess isolation** (`subprocess.run` on each tool’s CLI) so three separate `config` / `modules` trees never collide in one Python process.

---

## 5. Runtime layout (Mac dev)

| Path | Purpose |
|------|---------|
| `~/bidplus-runtime/` | Default `BIDPLUS_RUNTIME_DIR` (must stay **outside** `~/Documents` / iCloud) |
| `~/bidplus-runtime/venv/` | Single venv; install via `bash bidplus/scripts/setup_runtime.sh` |
| `~/bidplus-runtime/.env` | **One** `ANTHROPIC_API_KEY` for the whole system |
| `~/bidplus-runtime/hal/bids.db` | HAL tool DB (live: **139** rows in `tenders`, **136** Pass-1-scored) |
| `~/bidplus-runtime/isro/bids.db` | ISRO DB (live: **155** rows in `bids`, **154** Pass-1-scored) |
| `~/bidplus-runtime/gem/bids.db` | GeM DB (live: **11,333** rows in `bids`, **10,807** Pass-1-scored; **526** unscored from transient API drops — see §10.1) |
| `~/bidplus-runtime/hal/.browser_profile/` | Playwright profile (HAL) |
| `~/bidplus-runtime/logs/` | Per-portal subprocess logs from launcher (`<portal>_YYYYMMDD_HHMMSS.log`) |
| `~/bidplus-runtime/parent.db` | **Created (S3)** — WAL; `{hal,isro,gem}_bids` (139/155/11,333) + `users`/`scrape_runs`/`system_alerts`. Rebuildable any time via `launcher merge` |

Ubuntu deploy box: same structure under `/home/congo/bidplus-runtime/` per plan.

---

## 6. Excel — not part of the new tool

**Orchestrator path (`scrape-score` / `launcher run`):** no Excel ingest, export, or Pass 2. Phases are scrape → CLOSED sweep → Pass 1 only.

**Legacy standalone tools** still document `run`, `export-excel`, `ingest-excel`, `run-pass2` — human-review workflows from the samples. Running `isro_tool.py run` or `hal_tool.py run` **will** hit Excel export phases; that is **not** BidPlus.

**GeM-specific:** `gem_portal/modules/` does **not** ship `excel_ingest.py` / `excel_export.py`. S2 made top-level imports tolerant so `scrape-score` / `explain` work; Excel-only commands still fail if invoked. Restore those modules only if standalone GeM Excel is still required.

**Word “gap” in docs/output (disambiguation):**

| Term | Meaning |
|------|---------|
| `pass1_gaps` / `parsed_result.gaps` | Rubric field: capability/tech **missing from portfolio** for this bid |
| S2 “GeM gap” | Missing Excel **modules** in sample tree (engineering note, not product feature) |
| S3 “gap-aware merge” | Reconcile tool DB vs parent DB when row sets differ |
| `isro_portal/AGENTS.md` “Current gaps” | Known limitations list in old ISRO tool docs |

---

## 7. How to run (operator)

```bash
# One-time (Mac)
export BIDPLUS_RUNTIME_DIR=~/bidplus-runtime
bash bidplus/scripts/setup_runtime.sh
# Copy and fill key:
cp .env.example ~/bidplus-runtime/.env   # ANTHROPIC_API_KEY=...

# Full sequential pipeline (S2 DONE-WHEN — manual)
~/bidplus-runtime/venv/bin/python -m bidplus.launcher run

# Dry-run one bid (no API)
~/bidplus-runtime/venv/bin/python -m bidplus.launcher explain hal "<tender_number>" "<line_number>"
~/bidplus-runtime/venv/bin/python -m bidplus.launcher explain isro "<tender_id>"
~/bidplus-runtime/venv/bin/python -m bidplus.launcher explain gem "<bid_number>"
```

**HAL-only live run already performed:** ~375 s pipeline; `RunResult`: new=137, scored=132; Pass 1 batches showed frequent Gate 1 “missing IDs” retries (batch JSON didn’t include all tender keys — recovered via per-tender retry).

---

## 8. Git state

- **Commits on `main`:** `01dcde7` *S5 chunks 1–2 (two-pass eliminator + Haiku engine)* → `8bd76a6` *docs: eliminator V2 propagation + S0–S4 status* → `f9559cd` *feat(bidplus): orchestrator slices S0–S4* → `a228441` *initial*. Plus the latest **S5 C3** commit (governance loop + cutover + collision-review seed changes + this HANDOFF) — see `git log` HEAD. S0–S5 code, docs, eliminator seeds, and systemd units are **committed**.
- **S5 C3 committed:** `bidplus/governance.py`; `bidplus/scoring.py` (hard default + promoted-bypass), `bidplus/launcher.py` (rewired `run`, `promote`/`accept`/`governance-delta`/`governance-apply`), `bidplus/config.py` (governance pins); the 3 tools made scrape-only; seed edits `inscope_signals.json` (+5 pos) / `eliminator_keywords.json` (−`blade`).
- **Runtime-only, never committed (gitignored):** `parent.db` holds `eliminator_terms` (seeded + the 5 human pos adds + `blade` deactivated) / `eliminator_keyword_stats` / `list_change_proposals`; `$BIDPLUS_RUNTIME_DIR/list_review/{pending,ready,consumed}/` created; tool DBs carry live model/keyword scores from smokes.

Commit when ready; do not commit `~/bidplus-runtime/.env` or `*.db` (gitignored).

---

## 9. Per-portal technical notes

### HAL (S1)

- `hal_portal/src/modules/scorer_pass1.py`: JSON batch prompt with `matching_tech`, `recommendation`; two validation gates; stores in `tenders` table.
- `CAPABILITY_REF_PATH` → `bidplus.runtime.capability_reference_path()`.
- `cmd_scrape_score`: no Excel (contrast `cmd_run` Phase 0/4).

### ISRO (S2)

- Rubric: unified file via `capability_reference_path()` (no ISRO-specific rubric).
- `scorer_pass1.py`: `build_pass1_prompt(bids, cap_ref)`; parses full shape.
- `db.py`: `pass1_matching_tech`, `pass1_recommendation` + `_migrate()`.
- `scrape-score`: no Excel (contrast `cmd_run` Phase 4 “Export Excel”).

### GeM (S2)

- `scrape-score` / `explain` added; adapter mirrors HAL.
- Pass-1 bulk path still maps **score, confidence, domain, rationale, gaps** only in `explain` `parsed_result` — **no** `matching_tech` / `recommendation` in GeM DB/parser yet (plan allowed “GeM already on unified rubric”; full shape parity with HAL/ISRO is optional follow-up).
- Excel import workaround in `gem_tool.py` (see §6).

### Rubric consolidation (post-S2, main thread)

- **Single file:** `bidplus/data/capability_reference.md`
- **Resolver:** `bidplus.runtime.capability_reference_path()`
- All three `config.py` files point at it; old `*/data/capability_reference.md` **removed**

### Deferred (explicitly not done)

- Shared Pass-1 engine in `bidplus/` (still three `scorer_pass1.py` copies) → centralized at **S5**
- **Pass-1 scoring robustness** (from the live GeM run, §10.1) → **S5**: bounded retry-with-backoff on transient `APIConnectionError`/`529` (no skip-to-NULL), bounded concurrency to cut the ~3.5 h serial scoring time, duplicate-rationale gate that doesn't false-fire on similar junk
- Pre-Pass-1 eliminator **runtime gate + governance** (design frozen in `ELIMINATOR_DESIGN.md`; seeds built) → wired at **S5**: two-pass `neg & !pos` gate reading `eliminator_terms`; seed step; ledger; AI-delta → `list_change_proposals` → Excel review (`list_review/`); shadow→hard. New schema: `eliminator_terms`/`eliminator_keyword_stats`/`list_change_proposals` tables + per-bid `auto_rejected`/`human_disposition`/`human_reason` (plan §7)
- **Score-2 review** (`$BIDPLUS_RUNTIME_DIR/exports/score2_review.xlsx`, 411 rows) → human eyeball before the eliminator flips from shadow to hard (S5 cutover gate)
- **Pinned design items for S5** (user said "come back to"): *Issue 3* — GeM-only scoring intelligence (`few_shot_examples`, `feedback → promoted_to_rule`): decide **universal vs drop** when building the shared module; *Issue 4* — output-token budget as the binding constraint for batch sizing + retry (reinforced by the live run: output truncation, not input, drives 1:1 misalignment)
- Shared Sonnet summarization module → **S6** (Pass 2)
- `parent.db` merge → **S3**
- `fetch_documents` on adapters → **S6** (consumed by Pass 2; stays per-portal in the tool)
- GeM `matching_tech` / `recommendation` columns and parser alignment → optional cleanup
- Excel ingest/export (all tools) → **removed** per the redesign (no orchestrator Excel path)

---

## 10. Known issues / watch items

1. **GeM scoring robustness (526 unscored — fix held for S5):** the live GeM run left 526/11,333 bids with NULL `pass1_score`. Root cause: ~23 transient `APIConnectionError` batches — the in-tool `scorer_pass1._call_api` catches the error, returns the batch **unscored**, and the caller persists NULLs with **no retry/re-queue** (skip-and-NULL). Also slow: strictly serial **~28 s / 25-bid batch (~3.5 h, 445 batches)**, inflated by the Gate-2 duplicate-rationale check over-firing **45×** into per-bid retry storms on legitimately similar junk titles. **All three fixes — bounded retry-with-backoff on transient errors (never skip-to-NULL), bounded concurrency, and a duplicate-gate that doesn't false-fire — are recorded in the S5 slice** (plan §6 S5 Do/DONE-WHEN). The 526 rows are intact/re-scorable; re-running `gem_tool.py scrape-score` re-scores only the pending NULLs (but re-fetches all first, ~30 min wasted — no score-only command).
2. **Pass 1 Gate 1 retries (HAL/GeM):** Model often omits the PK in batch JSON (HAL: `tender_number`/`line_number`; GeM saw 26 missing-id retries); individual retries recover — noisy logs, not necessarily data loss. Folded into the S5 1:1-mapping requirement.
3. **Python version:** Plan pins 3.12 for Ubuntu; Mac dev used **3.13** in venv (`requires-python >= 3.12`).
4. **Workspace path:** Cursor workspace may detach from repo folder; use absolute paths and `BIDPLUS_RUNTIME_DIR` when running commands.
5. **Legacy docs:** Many `README.md` / `START_HERE.md` under portal folders still reference `data/capability_reference.md` and Excel flows — stale relative to orchestrator.

---

## 11. S3+ checklist for next agent

1. ~~Confirm S2 DONE-WHEN~~ — **done (live 2026-06-04→05):** three populated `bids.db`, Pass-1 fields sane, `explain` per portal. (Caveat logged: GeM finished standalone after a mid-run launcher interrupt; 526 GeM NULLs from transient drops, fix held for S5 — see §10.1.) **Start at S3.**
2. ~~Implement `parent.db` schema + gap-aware upsert~~ (S3) and ~~`scrape_runs`/sticky-alerts/tiered-gate/systemd~~ (S4) — **both done + validated.** Next: **S5** — shared scoring module + two-pass eliminator + governance (build to `ELIMINATOR_DESIGN.md`); centralize Pass-1 out of the tools, seed `eliminator_terms`, wire the gate shadow→hard, apply the scoring-robustness fixes (§10.1).
3. Do **not** reintroduce Excel into orchestrator paths.
4. Keep rubric edits only in `bidplus/data/capability_reference.md`.
5. **S5** centralizes Pass-1 + wires the **two-pass** eliminator gate + governance into `bidplus/` (Decision #9‑A; seed `eliminator_terms` from the two JSONs; ledger/AI-delta/Excel review; shadow→hard) — build to `ELIMINATOR_DESIGN.md`; **S6** builds Pass 2 (§8b summary). See plan §6/§7/§32 + `WEBAPP_HANDOFF.md`.

---

## 12. Quick reference — model & gate pins

From `bidplus/config.py` / `AGENTS.md`:

- Pass 1: `claude-haiku-4-5-20251001`
- Summary: `claude-sonnet-4-6` (S6+, Pydantic-validated)
- Score 5 → auto Pass 2 overnight; 4 → docs+extract (no summary), Sonnet on user click; ≤3 on demand; keyword-eliminated → score 0, skip model
- `SUMMARY_MAX_ATTEMPTS` default 3; `RETENTION_DAYS` default 7
- Sequential portals: `("hal", "isro", "gem")`

---

## 13. S6 (Pass 2) — RESUME HERE (2026-06-05)

S6 is built in **three channels**, all now wired. **Ch1 + Ch2 committed (`cc73a2c`, `73b58ae`). Ch3 + the score-gated wiring are built, real-Sonnet validated, and UNCOMMITTED** (review then commit). The only thing left before S6 DONE-WHEN is fully closed is a **full integrated `launcher run` on real scraped data** (deploy-box proof) and the commit; S7 (lifecycle + 7-day sweep) is next.

### ⚠ Uncommitted working-tree state (commit was deliberately deferred)
`git status` will show these modified/new, **none committed** — review then commit together:
- `bidplus/summarize.py` — **NEW**, Channel 3 (the §8b module) + score-4 `local_extract_bid` (NO Sonnet) + `unparsed_documents` surfacing.
- `bidplus/extraction.py` — local **single-vendor detection** (name-required, boilerplate-hardened) + **eligibility pre-flag** (`eligibility_preflag`, in `local_fields`).
- `bidplus/config.py` — `OUR_VENDOR_ALIASES` (default `["teclever"]`, env-overridable).
- `bidplus/launcher.py` — **`summarize` subcommand** (on-demand Pass 2; `--no-fetch`, `--local-only`) + **Pass-2 phase wired into `run`** (`_run_pass2`: score-5 Sonnet + score-4 local extract per portal).
- `bidplus/gate.py` — `work_pks()` (full, unsampled score-5/score-4 queues for the run).
- `bidplus/runs.py` — `record_portal`/`finalize_cycle` now persist `summarized_count`/`local_extracted_count`/`summary_failed_count`.
- `WEBAPP_HANDOFF.md`, `DEPLOY_WORKFLOW.md`, `HANDOFF.md` — doc updates (unreadable-docs surface; no-LibreOffice decision; Pass-2 in the service).

### Locked S6 design decisions (this session)
1. **DB stores ONLY the final summary** (`summary_json`, a Pydantic-validated structured object — *option 2*; render to markdown for display). NO temporary/extracted text in the DB.
2. **Extracted info lives in the per-bid folder** `$BIDPLUS_RUNTIME_DIR/<portal>/bids/<pk>/` as `.txt` files (+ original PDFs/images). The 7-day sweep (S7) clears them.
3. **Channel 2 = relevant text only** — no formatting, no embedded-image extraction. Drop non-English + governance/T&C boilerplate; keep technical/financial crux. Local extraction is *subtractive*; precise crux-selection is Sonnet's job at score 5. Purpose: cut Sonnet tokens + raise quality.
4. **Formats:** PDF/Word(.docx)/Excel(.xlsx,.xlsm)/PowerPoint(.pptx)/images native. **Legacy .doc/.xls/.ppt: LibreOffice is intentionally NOT installed** (operator decision 2026-06-05). The converter path stays in code (auto-activates if `soffice` ever appears on PATH) but is dormant; legacy/binary docs are marked `unsupported` and surfaced to the user as `unparsed_documents` in the summary (NOT sent to AI). The operator tallies occurrences to decide later whether `apt install libreoffice` is worth it. See WEBAPP_HANDOFF §4 + DEPLOY_WORKFLOW §2.
5. **Pure image / image-only PDFs → sent WHOLE to Sonnet** (vision; no local OCR). Embedded-image extraction from *mixed* text+image PDFs is **deferred** (DocExtractor at `/Users/kartrama/Documents/Projects/AI/DocExtractor` was the inspiration — we intentionally skip its formatting/image machinery to keep deps light; revisit only if summaries are weak).
6. **Single-vendor / single-tender decided LOCALLY (no Sonnet)** — GeM-style ("Single Tender Applicable: Yes" + named seller). Restricted to us (`OUR_VENDOR_ALIASES`) → favourable; to anyone else → dead. These bids skip Sonnet entirely (token saving). Sonnet keeps `single_vendor*` as a backstop for missed cases.
7. **Poison-pill / vendor-lock** (item mandated from a NAMED vendor/brand/OEM) → its own `vendor_lock_clauses` field, distinct from broad `eligibility_restrictions`. Added `buyer` + `location`.
8. **Output schema** = `summarize.BidSummary` (Pydantic): buyer, location, project_description, technical_scope, hardware_requirements, software_requirements, deliverables, implementation_timeline, submission_timeline, total_value, emd_value, pbg_value, vendor_qualification, eligibility_restrictions[], has_restrictive_eligibility, single_vendor, single_vendor_name, single_vendor_favourable, vendor_lock_clauses[], coverage. The Sonnet prompt is `summarize.PROMPT`.

### What `summarize.py` already does
`summarize_bid(portal, source_pk, parent, fetch=True, call_fn=None)`: fetch (if needed) → `extract_dir` → **if single_vendor: build local BidSummary, skip Sonnet** → else build content (cleaned text + whole image/scan blocks) → token-budget guard (oversized → primary text only, `coverage='partial'`) → Sonnet → parse → **Pydantic-validate with bounded retry** (`SUMMARY_MAX_ATTEMPTS`, default 3) → on exhaustion `summary_status='failed'` (logged, not re-queued) → **persist ONLY the summary** to `<portal>_bids` (`summary_json/model/generated_at`, `docs_summarized=1`, `summary_status`, `has_restrictive_eligibility`, `summary_coverage`). `render_markdown()` renders the JSON for display. **Two extra short-circuits before Sonnet:** (a) single-vendor → local record; (b) **nothing readable** (only legacy/binary docs, or no docs) → `local:unreadable-docs` summary, no Sonnet. Sibling **`local_extract_bid()`** is the score-4 path (regex `local_extract_json` + `local_extracted=1`, NO Sonnet). `unparsed_documents` (set locally) rides on both.

### Validated vs NOT
- ✅ No-API: single-vendor detection (us / other / open), mocked Sonnet path (parse→Pydantic→persist→render), markdown render.
- ✅ **Real Sonnet call DONE (2026-06-05)** — `summarize_bid` run against live `claude-sonnet-4-6` on GeM `GEM/2026/B/7605377` (primary text + scan PDF sent as a native `document` block). Summary quality is strong (buyer/location/technical scope/hardware/eligibility all captured; `single_vendor=false`, `has_restrictive_eligibility=true`, `vendor_lock=0` — all correct). **Two bugs found + fixed during validation:**
  1. **Single-vendor FALSE POSITIVE** — `detect_single_vendor` fired on the GeM GTC boilerplate clause "...except in case of Single Bid / Proprietary Article Certificate (PAC) Buying" (matched on RAW text, which keeps boilerplate), with no parseable seller name → was wrongly KILLED as "restricted to another vendor" and skipped Sonnet. Would have silently dead-ended a large fraction of GeM bids. **Fix (`extraction.py`):** dropped the boilerplate-prone prose signals (PAC, sole/single source), keeping precise ones (`single tender applicable: yes`, `single tender enquiry`, `on nomination basis`); and a single-tender hit with NO parsed name now returns `(False,"")` → falls through to Sonnet (whose `single_vendor` backstop still catches real ones). Honors decision #6 (signal **+ named seller**).
  2. **Prompt type mismatch → wasted retry** — attempt 0 returned `vendor_qualification` as a list and `eligibility_restrictions` as a string (schema is str / list[str]), failing Pydantic; the bounded retry recovered on attempt 1 but burned an extra Sonnet call per such bid. **Fix (`summarize.py` PROMPT):** added an explicit TYPES line (which keys are arrays / booleans / strings) + a `vendor_qualification` field rule. Re-validated → **validates on the FIRST attempt, no retry.**
- ✅ **Score-gated wiring DONE + tested (2026-06-05):** `launcher run` now runs a per-portal **Pass-2 phase** after merge — score-5 (`docs_summarized=0 AND summary_status IS NULL AND NOT CLOSED/keyword`) → Sonnet summary; score-4 (`local_extracted=0`) → `local_extract_bid` (regex `local_extract_json` + `local_extracted=1` + eligibility pre-flag, **NO Sonnet**). Counts flow to `scrape_runs` (`summarized_count`/`local_extracted_count`/`summary_failed_count`, per-portal + overall). On-demand **`summarize <portal> <pk…> [--no-fetch] [--local-only]`** added (the web "Retrieve information" trigger; `--no-fetch` = summarize from staged docs without re-fetch). Tested against the live parent.db: `work_pks` (gem: 22 score-5 / 164 score-4), real CLI `summarize` (first-try valid), `--local-only` (no Sonnet), and **unreadable-doc handling** — legacy-only bid → no Sonnet, `local:unreadable-docs` summary; mixed readable+legacy → Sonnet summary that still lists the `.doc` in `unparsed_documents`.
- ✅ **Unreadable-doc surfacing (user ask, 2026-06-05):** `BidSummary.unparsed_documents` (+ `local_extract_json.unparsed_documents`), set LOCALLY from `extraction.unsupported_docs` (never by the model), rendered prominently by `render_markdown()`. Web app reads it (WEBAPP_HANDOFF §4/§7).
- ❌ **NOT done:** the **full integrated `launcher run` on real scraped data** (deploy-box proof — Pass-2 runs after each portal's merge; verify counts + overnight budget). NOTE: the legacy/LibreOffice path is by-design dormant (not a gap) — `soffice` absent on the Mac; legacy bids correctly flag as unreadable.
- A fetched test bid already on disk: **GeM `GEM/2026/B/7605377`** (primary PDF text + 1 image-only spec → scan). HAL `HAL/KPT/ED/E-PROC/WC-1245/1|WC-1245` (7 docs) and ISRO `SA202600126601` (1 PDF) also fetched.

### Git
`07dc647` (frontend build + path rename) → `2b9b8f9` (S7: lifecycle + retention + budget) → `a66d62a` (S6 Ch3 + score-gated wiring) → `73b58ae` (Ch2) → `cc73a2c` (Ch1) → `910b1b1` (Pass-1 mapping fix) → `584fac2` (S5 C3) → `01dcde7` (S5 C1-2) → … . S7 committed as of `2b9b8f9`. **Deploy box provisioning is next (see §§ deploy checklist).**

---

## 14. S7 (lifecycle + retention + budget) — BUILT, dev-validated (2026-06-06)

`bidplus/lifecycle.py` (NEW) + wired into `launcher run` (after the gate, before finalize) + a standalone **`sweep`** command. Config: `OVERNIGHT_DEADLINE` (default `09:00`) added; `RETENTION_DAYS` reused.

- **`closed_sweep`** — parse each portal's closing-date column (HAL `closing_date` `DD-MM-YYYY HH:MM` / ISRO `bid_closing_date` `DD-Month-YYYY HH:MM` / GeM `end_date` ISO-8601-Z; cols+PK read from each adapter's `_SCORING`). Past-closing → `bid_status='CLOSED'` (parent row + `summary_json`/`local_extract_json` RETAINED), then delete that bid's staged files. Unparseable dates are skipped + counted. `bid_status` is mirrored, so the sweep runs LAST and re-closes after any merge re-open (self-healing).
- **`retention_sweep`** — delete staged files older than `RETENTION_DAYS`, keep newer (clicked-within-window bids keep files), remove emptied dirs. The deletion mechanism (not per-bid delete).
- **`reap_orphans`** — remove `bids/<pk>/` dirs that map to no parent row (crash leftovers); valid dirs always kept.
- **`budget_report`** — latest overall `scrape_runs` row: finished_at vs the next `OVERNIGHT_DEADLINE`; `within_budget` + duration + per-stage timings. `run` prints it and warns if over.

**Validated (synthetic, zero spend):** CLOSED marking across all 3 date formats + overlay retention + file removal; unparsed-date skip; retention age-split + empty-dir removal; orphan removal vs valid-kept; budget within/over; missing-table guard; `sweep` CLI end-to-end. **NOT done:** real full-cycle timing on the deploy box (shared with S6's deploy proof).

---

## 16. Web app (frontend) — ACTIVE (2026-06-09)

**Frontend** lives in `frontend/`; FastAPI serves `dist/` at `http://192.168.2.193:8000`
(deploy box, `bidplus-web.service`) and `http://localhost:8000` (Mac dev).
First nightly run completed 2026-06-09 01:00 IST: 3,492 new bids (HAL 23, ISRO 15, GeM 3,454),
3,492 scored, 24 AI-summarised.

### Current feature state (2026-06-09)

| Feature | Status |
|---------|--------|
| Login | Working. Enter key submits; double-submit guarded. |
| Dashboard | Working. Opportunity Distribution chips show **new / accepted** separately per score band (rejected excluded). Top stat tiles = New / Accepted (green). Single Tender amber chip shown when count > 0. |
| Bid list | Working. Sort = newest-first (`first_seen_date DESC`). Inline Accept/Reject buttons. Single Tender badge (green ★ Teclever / amber generic). Filter persistence via explicit return URL. |
| Bid detail | Working. Accept/Reject navigates to next bid in the filtered list (generation-counter pattern; no cancellation on navigate). Documents section with on-demand download (auto-fetches from portal if not cached; single file direct, multiple files ZIP). Single Tender banner (green/amber with org name). |
| Notifications | Working. Save-all bulk-rejects auto_rejected bids alongside clearing the governance queue. |
| System Alerts | Working. Panel shows nightly run history with per-portal breakdown (auto-scored / AI-scored / summarised). Alerts section below. |
| Activity log | Built, needs further browser validation. |
| Single Tender filter | Working. `?filter=singletender` → `WHERE is_single_tender=1`. |

### DB schema additions (2026-06-09)

All additive migrations, safe on existing databases.

| Table | New columns | Added by |
|-------|-------------|----------|
| `scrape_runs` | `keyword_scored_count INTEGER`, `model_scored_count INTEGER` | `merge.ensure_shared` |
| `{portal}_bids` (all 3) | `is_single_tender INTEGER DEFAULT 0`, `single_tender_org TEXT` | `merge.ensure_shared` + `_OVERLAY` |

### Single Tender detection (`bidplus/summarize.py`)

Detection runs on `.txt` extraction files. Regex matches `single tender applicable … yes`
(liberal, bilingual). Org extracted from `list of seller org … participation` field.

| Org classification | Action |
|--------------------|--------|
| Matches `teclever` (case-insensitive) | `pass1_score=5` → Sonnet summary auto-runs |
| Masked (`***` or empty) | `pass1_score=5` → Sonnet summary auto-runs |
| Readable, not Teclever | `auto_rejected=1`, `user_state='rejected'` |

**Timing:** automatically during Pass 2 for score 4/5 bids; on manual "Generate Summary"
for score 1-3 bids. Backfill command: `launcher singletender-backfill` (scans existing
`.txt` files, no re-downloads). First run on deploy box: 1 bid found and processed
(GEM/2026/B/7601663 — non-Teclever org, auto-rejected).

### Document download (`/api/portals/{portal}/bids/{key}/documents/download`)

- GET endpoint auto-fetches from portal if staging dir is empty.
- Single file → `FileResponse` (direct). Multiple files → ZIP stream.
- Frontend: `fetch()` with `credentials: include`; generation counter prevents stale
  state updates if user navigates away mid-download; file still saves to Downloads folder.

### Eliminator terms updated on deploy box (2026-06-09, DB only — not in git)

| List | Action | Terms |
|------|--------|-------|
| Neg phrase | Added 13 | air duct, beml drawing, beml drg, cleaning tool, conning tool, honing sticks, in finish condition, insurance service, mim route, mt spare, mt spares, through mim, video conferencing |
| Neg word | Added 4 | hammer, toluene, trolley, trolleys |
| Neg phrase | Deactivated 1 | fuel pump |
| Pos phrase | Added 3 | engine test bed, test bed, test stand |
| Pos token | Added 1 | vibration |
| Skipped | Already active | shop floor |

Note: `conning tool` added as specified (may be revisited for `coining tool`); `fuel pump`
deactivated pending review.

### Users on deploy box

`karthikeyan@teclever.com`, `sambath@teclever.com`, `radhika.s@teclever.com`,
`radhika.s@teclever.com` (password changed to `pop345ins`)

**Frontend-specific handoff doc:** `frontend/HANDOFF.md`

**Run commands (Mac dev):**
```bash
export BIDPLUS_RUNTIME_DIR=~/bidplus-runtime
~/bidplus-runtime/venv/bin/uvicorn bidplus.web.app:app --host 0.0.0.0 --port 8000 --reload
cd frontend && npm run dev   # hot reload; proxies /api → 8000
cd frontend && npm run build # production
```

**Recent commits (chronological):**
```
7344c5a  docs: add README
4d2dcf5  feat(runs): split scored_count into keyword_scored + model_scored
c77cb9d  feat(ui): dashboard new/accepted split, filter persistence, next-bid navigation
2980f83  fix(dashboard): defensive ?? 0 on new score-band counts
9e9278f  fix(bid-detail): clear stale state on bid change, fix back button destination
72b5e7a  fix(bid-detail): skip current bid key in navigateToNext
65a78b0  feat(docs): single Download documents button in bid detail
35d96d9  fix(docs): single file → direct download, multiple files → ZIP
861301f  fix(docs): proper error handling for document download
1e08ba7  fix(docs): cancel in-flight download on navigation
91458eb  fix(docs): let download complete even after navigation
d21a3eb  feat(single-tender): detect, highlight, filter Single Tender bids
```

**Governance loop (`bidplus/governance.py`) — fully implemented:**
- `promote()` / `accept()` wired to web `/dispute` + `/save-all` endpoints
- `ingest_ready()` runs at the start of every `launcher run`
- `generate_delta()` via `launcher governance-delta`
- Full loop fires once ~35 promotions accumulate or weekly

---

## 15. Web/API layer (`bidplus/web/`) — BUILT + smoke-validated (2026-06-06)

The web round's **backend API** is built in-repo (the front-end is a separate handoff —
`webapp-design/`). Authoritative spec: **`webapp-design/WEBAPP_DESIGN.md` §16**; the front-end
contract is **`webapp-design/API.md`**. Stack: **FastAPI**, reusing bidplus modules directly.

- **`bidplus/web/`** — `app.py` (all endpoints: auth, per-portal stats, listing w/ filters+search,
  bid detail, generate-summary, disposition, notifications, activity, system-alert; serves
  `frontend/dist` static if present), `schema.py` (new tables), `auth.py` (DB-session cookie),
  `passwords.py` (bcrypt + `@teclever` guard), `mapping.py` (per-portal column→normalized field map).
- **`bidplus/locks.py`** — `flock` on `$RUNTIME/summarize.lock`; web generate-summary takes it
  NON-blocking → `409 summarization_busy`; nightly `_run_pass2` holds it (blocking) around the
  score-5 loop. **One path to Sonnet, never entered twice at once.**
- **`bidplus/dispositions.py`** — accept/reject writes `user_state`+`disposed_*`+an `activity_log`
  row in one txn; `log_activity` also records notification disputes.
- **`bidplus/users.py`** — `python -m bidplus.users {add|edit|remove|list}`, run MANUALLY on the
  deploy box (bcrypt, `@teclever` email enforced). No self-signup, no web admin.
- **New `parent.db` tables** (additive, `bidplus.web.schema.ensure_web_schema`): `sessions`,
  `activity_log`, `notification_views`. No new bid columns — the per-user notification watermark
  reuses each table's existing `first_seen_date`.
- **Deps added** (`pyproject.toml`): `fastapi`, `uvicorn`, `bcrypt`. Run:
  `uvicorn bidplus.web.app:app --host 0.0.0.0 --port 8000`.

**Smoke-validated** (FastAPI TestClient against a copy of the live `parent.db`, zero spend):
unauth→401, wrong-password→401, non-teclever→422, login/`/me`/logout, stats for all 3 portals
(7-day window date + buckets), listing incl. `closingsoon`, **HAL composite-key** detail,
disposition→activity row, notifications queue/count/viewed. **NOT exercised:** live
`generate-summary` (real Sonnet call — needs API key + network; the lock/409 path is wired) and a
real browser front-end (built separately from `webapp-design/`).

## 17. Post-deploy changes (2026-06-18 / 2026-06-19) — DEPLOYED & LIVE

System is live in daily use. These changes were committed, deployed to the box, and validated.

### 17.1 Fourth portal — HAL Corporate Tenders (`halc`)
- New portal key **`halc`** = HAL corporate tenders site `hal-india.co.in/tender` (WordPress REST
  behind a WAF; browser-header cookies warmed). **Distinct from `hal`** = HAL e-Procurement
  (`eproc.hal-india.co.in`). Commit `20d93d5` (+`12915ef`, `388fea4`).
- New tool `halc_portal/` (seeded from the standalone HAL-corporate tool, adapted to the
  integrated `isro_portal` shape: `scrape-score`/`explain`/`fetch-docs` + standalone run/pass2;
  PK `tender_id`, text `tender_description`, extra `ref_no`/`category` cols). New adapter
  `bidplus/adapters/halc.py` (`HALCAdapter`). `halc` wired into every portal registry
  (`config.PORTALS` = hal,halc,isro,gem; merge `_ADAPTERS`/`_SOURCE_TABLE`/single-tender loop;
  scoring, governance(×4 dicts: `_ADAPTERS`,`_ADAPTER_PK`,`_ADAPTER_TEXT`), summarize, lifecycle,
  launcher, web app `_make_adapter`, web/mapping `PORTAL_FIELDS`, dispositions/gate `_PK`).
  **Lesson: portal-keyed dicts are scattered — grep `"isro"`/`"gem"` (single- AND multi-line).**
- Frontend: `PortalId` adds `halc`; Dashboard is a **4-card** grid (`md:grid-cols-2 xl:grid-cols-4`),
  existing HAL relabelled "HAL e-Procurement", new "HAL Corporate Tenders" card.
- **HALC Bid ID = `ref_no`** (T_REF_NO, e.g. `TENDER NOTICE/NCP/21/26-27`), not the internal
  numeric `tender_id` (which stays the PK/bidKey). `mapping.bid_id_display`. Commit `4d4736f`.
- **HALC documents — two sources** (`fetcher.download_documents`): direct `tendorfile*`/`Corrigendum*`
  PDFs, OR for "Refer NIT … visit eproc" tenders, follow `T_RETURN_URL` → `PublicDocumentDisplay`
  → download each `DownloadController` file in the SAME (session-scoped) e-proc session, skipping
  File ID `--` placeholder rows. Fixes "no machine-readable documents". Commit `4d4736f`.

### 17.2 Single → Single/Limited Tender detection
- Restriction detection now triggers on **`Limited Tender Applicable: Yes`** too (not just Single
  Tender), reading the same `List of Seller Organization for participation` field and routing
  through the existing classifier: named-non-Teclever → auto-reject; Teclever → score 5; **masked →
  score 5 + `is_single_tender=1`, surfaced for human review (never auto-accepted)**. Commits
  `e6e598c`, `b3c1dfc`. Frontend relabel "Single Tender" → "Single / Limited Tender".
- **Critical fix:** detection now runs on **RAW pdf text** (`_raw_staging_text`), not the cleaned
  `.txt` sidecar — `clean_text` strips the boilerplate/Devanagari-heavy GeM table section that holds
  the tender-type + seller-list fields, so regex on cleaned text silently missed it (single tenders
  were only caught via the Sonnet `single_vendor` fallback, which never fires for a limited list).

### 17.3 Reset accepted bids (UI)
- "Reset to New" now shows for **any disposed bid** (accepted *or* rejected) on the detail page, and
  as a per-row action in the bid list (table + card). Backend `reset` disposition was already
  state-agnostic. Commit `4d61191`. (No bulk reset — bulk endpoint is accept/reject only.)

### 17.4 Remote control plane (`bidplus-control`) — NEW SUBSYSTEM
- Box is outbound-only; a Google Sheet is the rendezvous. `bidplus-control.service` (systemd,
  `User=congo`, auto-restart, reboot-safe) polls a Sheet and writes run status back — all outbound.
  Reports autonomous nightly runs too. Commits `eff9fe5`,`a5ab925`,`9095cf6`,`53cdd28`.
- Code in `bidplus/control/`; full operator doc in **`bidplus/control/README.md`**. Two whitelisted
  commands only: `run` (all portals) and `rerun <portal>` (= `launcher run --only <portal>`, added).
  Sheet tabs: `Status` (heartbeat + per-portal counts), `Runs` (history), `Commands` (operator
  queues here), dated `Nightly`/`Run`/`Rerun` bid-list tabs (Portal·BidID·Title·Org·Pass1·Summary,
  score-desc, score 5/4/3 conditional fills, filter, wrap; rerun tabs = upserted-only delta).
- SA key `/etc/bidplus/bidplus-control-1b58558711e0.json` (`bidplus:bidplus 600`); congo granted
  read via `setfacl -m u:congo:r` (needs `apt install acl`).

### 17.5 Ops note
- A **manual `merge` must be followed by `sweep`** (the nightly does merge→sweep, sweep last): a
  bare merge mirrors tool `bid_status` and can briefly re-open past-closing bids until the sweep
  re-closes them. `merge --check` showing `bid_status` mismatches right after a sweep is expected
  (parent is authoritative for CLOSED via the sweep).

*End of handoff. Update this file when a slice DONE-WHEN passes or when validation state changes.*

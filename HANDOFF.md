# Teclever Bid Portal — Development Handoff

**As of:** 2026-06-04  
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
| **S4** Hardening | `scrape_runs`, sticky alerts, systemd timer, tiered queues | **Done + validated (2026-06-05)** | `runs.py` + `gate.py` + launcher cycle/`gate`/`run-status` + systemd units. **Validated (17 checks):** in-progress overall row (`finished_at IS NULL`) then finalized; 1 overall + 3 per-tool rows w/ counts + stage timings; failed portal → `failed` for it, **`partial`** overall, others finish; partial/failed raises **sticky** `system_alerts` (a later success leaves it active); all-failed → `failed`; tiered gate buckets 5/4/≤3 (auto5=23, local4=168) with **CLOSED + keyword excluded** (NULL-safe), matched to manual SQL. **Timer firing** = deploy-box (systemd) verification, units shipped. |
| **S5** Shared scoring module + eliminator | centralize Pass-1 out of the tools; normalized-record seam; **two-pass** eliminator gate (`neg & !pos`, read from `eliminator_terms` DB) shadow→hard; ledger + AI-delta + Excel governance; output-budget batching; 1:1 mapping; transient-error retry | **Not started — design FROZEN** (`_oldFiles/EliminatorDesignV2/ELIMINATOR_DESIGN.md`). Seeds present in `bidplus/data/`: `eliminator_keywords.json` (689 neg) + `inscope_signals.json` (237 pos); miner built. Gate/governance wiring + centralization pending | — |
| **S6** Pass 2: docs → summary | `fetch_documents`, local extract, **one** Sonnet summarization path | **Not started** (`fetch_documents` → `NotImplementedError` on all adapters) | — |
| **S7** Lifecycle | CLOSED sweep hardening, 7-day file retention | **Not started** | — |

**S2 + S3 + S4 DONE-WHEN: satisfied (2026-06-05).** **Next slice = S5 (shared scoring module + two-pass eliminator + governance — build to `ELIMINATOR_DESIGN.md`).** *(S2 caveat retained: GeM finished standalone after a mid-run interrupt; substance met. S4 timer firing is the one item deferred to deploy-box systemd verification — units shipped in `deploy/systemd/`.)*

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

- **Latest commit:** `a228441` — *Initial commit: backend action plan, AGENTS rules, deploy runbook, and sample portal tools*
- **Uncommitted (working tree):** entire `bidplus/` package (incl. **new `bidplus/merge.py`** (S3), **`bidplus/runs.py`** + **`bidplus/gate.py`** + rewritten launcher with `merge`/`gate`/`run-status` commands (S4), and the `bidplus/data/` eliminator seeds `eliminator_keywords.json` + `inscope_signals.json`), **new `deploy/systemd/bidplus.{service,timer}`**, `pyproject.toml`, `.env.example`, tool modifications (HAL/ISRO/GeM), doc updates (`AGENTS.md`, `MASTER_ACTION_PLAN_V3.md`, `WEBAPP_HANDOFF.md`, `DEPLOY_WORKFLOW.md`, `isro_portal/AGENTS.md`), **deletion** of per-portal `data/capability_reference.md` (replaced by `bidplus/data/`)

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

*End of handoff. Update this file when a slice DONE-WHEN passes or when validation state changes.*

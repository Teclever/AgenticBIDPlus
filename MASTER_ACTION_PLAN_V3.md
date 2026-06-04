# Master Action Plan & WBS — Teclever Bid Portal
## Agent-Ready Backend Build (Slices S0–S6)

> **Audience:** an agentic coding tool (Claude Code primary; Cursor secondary).
> **Framing:** treat this as **greenfield development**. The three existing tool
> folders (`gem_portal/`, `hal_portal/src/`, `isro_portal/`) are **fully functional
> code samples** — the scrape, file-download, Pass 1 scoring (Anthropic), and DB-write
> logic are all known-good and should be **reused/adapted**, not reinvented.
> **This document covers the backend only.** The web app is a later round; its **API
> contract and UI are deferred** (see §9). The **structured per-bid summary is computed
> in this backend round** (no longer deferred).

---

## 1. What we are building (backend)

A parent **orchestrator** runs each portal's existing pipeline **sequentially**
(HAL → ISRO → GeM), letting each populate **its own** SQLite (as today). The orchestrator
then **upsert-merges** each tool DB into a **parent DB** that holds **one table per
portal**. Bids scoring **≥ 4** under a **single unified rubric** have **all their documents
fetched** into a **per-bid directory** and **saved locally** (every score, score 5 included);
text is extracted from text-based docs, scanned/image files are retained. A **single
score-agnostic summarization module** then feeds **extracted text + the non-text files** to
**Sonnet 4.6** (it reads scans/images natively via vision — no local OCR, no vector DB),
**validates the result with Pydantic**, and stores a **structured summary**. The module is
**triggered** by score: **5** runs it overnight; **4** gets only a cheap **regex preview**
overnight with the module **deferred** to a "Fetch more information" click; **3** is fetched
on demand. Previews and summaries live in the DB. Downloaded files are **staged, not
hoarded** — a strict nightly sweep deletes anything older than **7 days**. The web app, which
displays this, comes after. The whole cycle runs overnight and must finish before users arrive.

---

## 2. Decision log (locked)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Score tiering (trigger only) | The **Sonnet summarization module** (#24) is **identical for all scores** — only its **trigger** differs. **Score 5 is the ONLY automatic Sonnet call (overnight).** **Scores 4 and below go to Sonnet ONLY after explicit user confirmation** ("Fetch more information"): **4** has a **regex preview** + docs staged & text-extracted overnight (module on click); **3** fetches + module on click; **2/1/0** module only on a forced click. **CLOSED bids are excluded — no fetch/extract/summarize, ever** |
| 2 | Deployment | Single Ubuntu 24.04 LAN desktop (i3-7100U, 7.6 GB RAM, 4 GB swap, **~100 GB root LV** — 931 GB physical, 828 GB unallocated in `ubuntu-vg`, extendable via `lvextend` at deploy time), ~5 users, NAT'd broadband |
| 3 | Run observability | **No email.** Every run logged to `scrape_runs` (with per-stage timing). A failed nightly cycle raises a **sticky alert** (`system_alerts`, §7) shown in the web app's Runs/Logs view that **persists until a human explicitly clears it** — it is **not** auto-cleared by a later successful run. Backend (S4) raises it; the web-app round renders the banner + a user-attributed "clear" action |
| 4 | DB architecture | **Two-tier:** each tool keeps its own SQLite; gap-aware **full-reconciliation upsert** into a parent DB |
| 5 | Parent DB shape | **Separate table per portal** (`gem_bids` / `hal_bids` / `isro_bids`), each mirroring its tool schema + overlay columns. Shared `users`, `scrape_runs` |
| 6 | Overlay columns | Live **inside each portal table** (`local_extract_json`, `docs_summarized`, `summary_json`, `has_restrictive_eligibility`, `user_state`, disposition…) |
| 7 | Data layer | Consolidated **SQLite (WAL)** only — **no vector store, no local embeddings.** Local structured extraction + Sonnet summaries live in the DB; downloaded files are staged in **per-bid directories** (see #29) |
| 8 | Rubric | **Unified** Pass-1 rubric across all portals. **ISRO re-scores** under the detailed rubric; its Pass 1 parser moves to the full output shape (`MATCHING TECH`, `RECOMMENDATION`) |
| 9 | Scoring code | **Medium extraction:** shared Pass-1 *engine* (prompt build / batch call / validation / parse); **per-portal input-field assembly stays separate** |
| 10 | Lifecycle | Accept/reject + forced disposition (web-app round). On reject/CLOSED, **retain the parent DB row + its data**; nightly sweep marks CLOSED. Document **files** are governed by the 7-day retention sweep (#29), not deleted per-bid immediately |
| 11 | On-demand fetch | Score-5 summaries are precomputed overnight. **Score-4 "Fetch more information"** sends the bid's **locally-stored** text + retained scanned files to Sonnet (no re-fetch within the 7-day window) — same **§8b module**, user-triggered. Score-3 fetches on demand. Single global lock. The **trigger** is web-app round; the **module** is built at S5 |
| 12 | Web stack | FastAPI JSON API + React SPA, **built on dev machine**, only static `dist/` deployed (web-app round) |
| 13 | UI model | **Portal-segmented**: pick GeM/HAL/ISRO first (web-app round) |
| 14 | Auth | Per-user, **CLI-provisioned**, **argon2/bcrypt-hashed**, no self-service flows (web-app round) |
| 15 | Tooling | **Claude Code primary**, Cursor secondary. Canonical **`AGENTS.md`** + thin `CLAUDE.md` pointer + a one-line Cursor rule |
| 16 | Build order | **HAL first** (retire the Playwright-on-headless risk on day one), then ISRO + GeM |
| 17 | Verification | **Pinned/deferred.** Per-slice **manual validation** (run + dry-run view + DB compare). Revisit automated tests later |
| 18 | Dev vs deploy | **Develop on Mac** (repo root `~/Documents/Projects/AI/BidAnalysisPortal/`, new code under `bidplus/`); **deploy on the Ubuntu server** `congo@tecleverbidplus` (repo root `/home/congo/BidAnalysisPortal/`). Source is git-versioned; **git pull** on the server. Concrete trees for both machines in §5b |
| 19 | Runtime paths | **Config-driven** via `BIDPLUS_RUNTIME_DIR`. Source stays in iCloud-backed Documents; **venv + per-bid document staging + runtime DBs + `.env` live in a runtime root *outside* iCloud** (Mac: `~/bidplus-runtime/`; Ubuntu: `/home/congo/bidplus-runtime/`). Identical structure on both machines; only the root differs |
| 20 | Tool DB relocation | Each tool's `config.py` is made **env-overridable** so its `bids.db`/`downloads`/`exports`/`.browser_profile` resolve under `$BIDPLUS_RUNTIME_DIR/<portal>/` (falls back to in-tree default when unset, preserving standalone runs). `config.py` **fails loud** if the runtime dir is inside iCloud |
| 21 | Repo boundary | Git root = **`BidAnalysisPortal/`** (new `bidplus/` + the three tool folders, since the server needs the tool code). `git init` at S0; `.gitignore` excludes all `*.db`/`-wal`/`-shm`/`exports`/`downloads`/`.browser_profile`/`.env`/`*.nosync`. (No `bids/` entry needed — the `bids/<source_pk>/` document staging lives under `$BIDPLUS_RUNTIME_DIR`, **outside the git tree**; an unanchored `bids/` would also wrongly ignore any future in-tree dir of that name.) |
| 22 | Document acquisition | **Per-portal, via the adapter.** HAL/ISRO **enumerate all documents** from the tender's document-view and download each. GeM lists **only one primary PDF** → **parse it for supporting-doc links** (`extract_spec_links`) → fetch those (`_download_spec_pdf`). The adapter owns this difference |
| 23 | Document formats | Any format — text PDF, **scanned/image-only PDF**, standalone images, **Word**, **Excel**. **No local OCR.** Native text/Word/Excel → **extract text locally** (stored; source file discarded). **Scanned/image** docs → **retain the file** for Sonnet to read natively (vision). Everything lands in the per-bid directory |
| 24 | Summarization module | A **standalone, score-agnostic module** — the **single path for anything sent to Sonnet**. Input = **extracted text** (from text-based docs, via regex/pdfplumber/python-docx/openpyxl) **+ the non-text files** (scanned/images as document/image blocks). **Sonnet 4.6** (`claude-sonnet-4-6`), one structured call → output **validated with Pydantic** (**bounded retry** — default 3 attempts — then **mark `summary_status='failed'` + log + manual review**, never an open loop) → stored in `summary_json` → served to the user. Triggered per #1 (auto@5 / on-click@4 / on-demand@≤3). **No map-reduce:** a bundle that fits context (the usual case) is **one** call; a rare oversized bundle falls back to summarizing the **primary tender doc(s) only**, marks the result **`coverage='partial'`**, and **flags the bid for manual review** |
| 25 | Extraction rigor | The summary prompt **discards non-English text and generic boilerplate**, but **keeps project-specific T&C**. Boilerplate patterns are catalogued from **real portal samples** in a **parallel side-quest** (sample review), then folded into the prompt + per-portal skip-lists |
| 26 | Eligibility flags | The summary **prominently highlights restrictive participation clauses** — mandated specific hardware, named tools/technologies, vendor-tied software licenses, or any criterion written to limit who can bid. These are go/no-go signals and get their **own field + a boolean flag** |
| 27 | Overnight budget | The full cycle (scrape → Pass 1 → merge → fetch + local-extract + score-5 summarize) starts in the low-usage window (**~3–4 am**) and must finish **by ~9 am**. The orchestrator logs **per-stage durations** to `scrape_runs`. Expected ≥4 volume is **tens/night (≈30–40), not hundreds** |
| 28 | Local extraction (score 4) | Best-effort **regex + heuristics** over the extracted text: EMD, total value, key dates, qualification keywords, and a **keyword pre-flag for restrictive-eligibility**. Stored in `local_extract_json` and shown immediately; narrative fields (clean description, deliverables) are filled by the Sonnet module on click. **Score 5 skips this preview** — it runs the Sonnet module directly. Reuses the samples' `extract_emd_amount` / `contract_value` regex |
| 29 | File retention & sweep | Downloaded docs are staged in **`$BIDPLUS_RUNTIME_DIR/<portal>/bids/<source_pk>/`** (native files discarded once their text is extracted; **scanned/image files kept**). A **strict nightly sweep deletes anything older than 7 days** — this **replaces the old delete-immediately rule**. (The working set is small — ~40 bids × ~50 MB × 7 days ≈ **~14 GB**, which fits the deploy box's **~100 GB root LV** comfortably — so **no disk-high-watermark is needed**; reliability of the 7-day sweep is what matters. Headroom exists if ever required: 828 GB sits unallocated in `ubuntu-vg` for an `lvextend` at deploy time.) A late (>7-day) "Fetch more" click finds the staged files gone, so the **§8b module re-fetches** the documents — possible only while the bid is still open; a **CLOSED** bid does nothing (terminal). *(Only `local_extract_json` survives the sweep in the DB — full text is not separately persisted.)* |
| 30 | Deploy is a separate phase | The **Ubuntu box is a deploy-phase dependency, not a build-phase one** — all slices S0–S6 are built and validated on the **Mac**; the box need not be available during development. Deploy-box bring-up (incl. optional `lvextend`, systemd units, Ubuntu `playwright install --with-deps`, eMudhra→certifi, **proving headless Chromium on the box**), the **git-pull-on-box** deploy, and **same-LAN SSH smoke-testing** of each changed lane (scrapers / orchestrator / summarizer / future middleware+React) are specified **standalone** in **`DEPLOY_WORKFLOW.md`** — agent-executable on its own. Deploys are commit-atomic; runtime state + secrets live under `$BIDPLUS_RUNTIME_DIR` (gitignored) so a checkout can never clobber them. |

---

## 3. Target architecture

```
   ┌──────── ORCHESTRATOR (systemd timer, ~3am, SEQUENTIAL: HAL → ISRO → GeM) ───────────┐
   │   launches each portal's existing pipeline; writes scrape_runs (+ per-stage timing)  │
   │      │ via PortalAdapter                                                             │
   │      ▼                                                                               │
   │   [tool SQLite: hal/isro/gem]  ──upsert-merge──▶  [PARENT SQLite]                    │
   │      │                                              gem_bids / hal_bids / isro_bids  │
   │      │ Pass 1 (unified rubric, Haiku)               users / scrape_runs              │
   │      ▼                                                                               │
   │   score ≥ 4 ─ fetch all docs (per-portal) ─▶ bids/<source_pk>/  (saved locally:       │
   │                    │                          native→text extracted, scans retained)  │
   │       ┌────────────┴─────────────┐                                                   │
   │   score 5                     score 4                                                │
   │   §8b module now              local regex preview → local_extract_json                │
   │   (text+scans→Sonnet→             (module deferred to user "Fetch more" click)        │
   │    Pydantic→summary_json)                                                            │
   │       └────────────┬─────────────┘                                                   │
   │                    ▼                                                                 │
   │            [PARENT SQLite: local_extract_json / summary_json]                         │
   │            files swept nightly at 7 days (not deleted per-bid)                        │
   └─────────────────────────────────────────────────────────────────────────────────────┘
                    (web app reads the parent DB + summaries later; cycle must finish by ~9am)
```

---

## 4. Invariants (the agent must never violate)

- **Reuse the samples.** Scrape, download, Pass 1, and DB-write logic are known-good — adapt them; do not rewrite from scratch.
- **Touch portals only through `PortalAdapter`.** Do not re-implement portal transport (`fetcher.py`, HAL `session.py`, GeM `csrf_handler.py`) — wrap it.
- **Strictly sequential** scraping; **one** heavy operation at a time (dual-core CPU).
- **Parent merge is always UPSERT.** Never blind-insert; **never overwrite any overlay column** on a re-merge — neither AI-derived (`local_extracted`/`local_extract_json`/`docs_summarized`/`summary_json`/`summary_model`/`summary_generated_at`/`has_restrictive_eligibility`/`summary_coverage`) nor human (`user_state`/`disposed_by`/`disposed_at`). All overlay is parent-owned and written once.
- **EXTENDED is a minimal update — nothing else happens.** When a bid is extended, the tool flips `bid_status`/`extension_count` and the closing date moves; the merge just **mirrors those tool-owned fields** (`bid_status`, `extension_count`, `closing_date`) like any other synced field. **No overlay is touched and the bid is NOT re-summarized** — an existing summary stays as-is. There is no re-summarize trigger anywhere; a bid is summarized at most once.
- **No vector store, no local embeddings, no local OCR.** Sonnet reads documents (incl. scans/images) natively. Don't reintroduce a vector DB or an embedding model.
- **Documents are staged, not hoarded.** Downloaded files live in per-bid dirs `$BIDPLUS_RUNTIME_DIR/<portal>/bids/<source_pk>/`; native-text files are discarded once their text is captured, **scanned/image files are kept** for Sonnet. A **nightly 7-day sweep** is the deletion mechanism — there is no permanent document archive. The DB (local extraction + Sonnet summary) is the durable artifact.
- **Documents are saved locally for every fetched bid** (score 5 included), and text is extracted, before anything is sent to Sonnet.
- **Score tiering is trigger-only:** the summarization module is identical for all scores; only *when* it runs differs. **Score 5 is the only automatic Sonnet call.** **Scores 4 and below must NOT be sent to Sonnet without explicit user confirmation** — score 4 shows a regex preview and runs the module on a "Fetch more" click; score 3/2/1/0 run the module on demand.
- **One path to Sonnet:** all document summarization goes through the single **§8b module** — extract text → send text + non-text files → Sonnet → **Pydantic-validate** (never store an unvalidated/malformed result; **bounded retry then mark `failed` + log**, never loop) → store. Summarize once per bid (idempotent on `docs_summarized=1`); **a bid is never automatically re-summarized** — EXTENDED only updates the flag + closing date, and re-running the module on an already-summarized bid is a no-op.
- **Restrictive-eligibility clauses are always surfaced** in the summary (own field + flag) — they are go/no-go signals.
- **CLOSED is terminal — no AI work on a CLOSED bid.** Never fetch documents, run local extraction, or summarize a CLOSED bid: the tiered gate skips it, and a later "Fetch more" click on a CLOSED bid does nothing.
- **`ANTHROPIC_API_KEY` from environment**, never hardcoded. **One** key, injected by the orchestrator — do **not** create per-tool `.env` files as a second source of truth.
- **No writable state in the synced tree — including the tool DBs.** Each tool's `bids.db` (+ `-wal`/`-shm`), `downloads/`/`exports/`, HAL's `.browser_profile/`, **and the orchestrator's `bids/<source_pk>/` document staging** must resolve under `$BIDPLUS_RUNTIME_DIR/<portal>/`, not inside the iCloud-synced source. A live SQLite syncing mid-write is the sharpest corruption risk in the system. (This guard is Mac-specific; on the Ubuntu deploy box there is no iCloud.)
- **Build in slice order S0→S6.** Do not start a slice until the previous slice's **DONE-WHEN** is met.
- **Expose a dry-run/explain view** (input fields → prompt → parsed result) so the human can validate scoring/summarization manually.

---

## 5. Pinned technical choices (defaults — correct later if needed)

| Concern | Pin |
|---------|-----|
| Python | 3.12 (ships with Ubuntu 24.04) |
| Env | **one** venv — created in `$BIDPLUS_RUNTIME_DIR/venv`, **outside iCloud** (never inside the Documents-synced tree) |
| Dependencies | Union of the three tools + `playwright` (HAL); **document extraction: `pdfplumber`/`pypdf`, `python-docx`, `openpyxl`/`pandas`** (text/Word/Excel — scans/images go to Sonnet, **no local OCR**); **`pydantic`** (validate the Sonnet structured output); `fastapi`/`uvicorn` (later). **Pin `certifi==<version>`** so a deps install never silently overwrites the eMudhra→certifi append the GeM TLS fix relies on (see `DEPLOY_WORKFLOW.md` §2). **Removed:** `chromadb`, `sentence-transformers` |
| Pass 1 model | `claude-haiku-4-5-20251001` (batch scoring) |
| Summary model | `claude-sonnet-4-6` — one structured call per bid, reads docs natively (vision). **Auto for score 5; deferred-on-click for score 4** |
| Local extraction | Score-4 only: regex/heuristics (EMD, value, dates, qualification keywords, eligibility pre-flag) → `local_extract_json` |
| File retention | Per-bid dirs under `$BIDPLUS_RUNTIME_DIR/<portal>/bids/`; **strict nightly sweep deletes files > 7 days old** (~14 GB working set fits the ~100 GB root LV — no high-watermark needed) |
| Parent DB | SQLite, **WAL mode**, in `$BIDPLUS_RUNTIME_DIR`, separate per-portal tables + shared `users`/`scrape_runs` |
| Scheduler | systemd timer, sequential, ~3am start, must finish by ~9am |
| Secrets | `.env` in `$BIDPLUS_RUNTIME_DIR` (outside iCloud + outside git) → loaded into environment; never committed |

---

## 5b. Environments & runtime paths (dev vs deploy, iCloud-safe)

**Hard rule:** **source = versioned + backed up; runtime state = machine-specific, never
synced, never committed.** All runtime paths are derived from a single env var
`BIDPLUS_RUNTIME_DIR`, which **must point outside iCloud** on the Mac.

| | Development | Deployment |
|---|-------------|------------|
| Machine | **Mac** (iCloud present) | **Ubuntu** `congo@tecleverbidplus` (no iCloud; the low-spec box) |
| Source (git root) | `~/Documents/Projects/AI/BidAnalysisPortal/` *(iCloud-backed — fine, it's small)* | `/home/congo/BidAnalysisPortal/` *(git pull)* |
| `BIDPLUS_RUNTIME_DIR` | `~/bidplus-runtime/` *(**outside** Documents/Desktop → iCloud won't touch it)* | `/home/congo/bidplus-runtime/` |
| Holds | `venv/`, `.env`, `parent.db`, **and per-portal `<portal>/` dirs** (each tool's `bids.db`, the `bids/<source_pk>/` document staging, `exports/`, HAL's `.browser_profile/`) | same |

Concrete layout — **both machines**. The runtime structure is identical; only the roots
differ.

**Development — Mac**

Source (git, iCloud-backed):
```
~/Documents/Projects/AI/BidAnalysisPortal/          ← git root
  bidplus/                          ← new orchestrator (this build)
  gem_portal/  hal_portal/src/  isro_portal/        ← reused sample tools
  MASTER_ACTION_PLAN_V3.md  AGENTS.md  …
  UIReference/                      ← web-app round (later)
```
Runtime — `BIDPLUS_RUNTIME_DIR=~/bidplus-runtime/` (**OUTSIDE iCloud**):
```
~/bidplus-runtime/
  venv/   .env   parent.db
  gem/    bids.db  bids/<bid_number>/…              state.json
  hal/    bids.db  bids/<tender_number>_<line>/…    exports/  .browser_profile/
  isro/   bids.db  bids/<tender_id>/…               exports/
```

**Deployment — Ubuntu (`congo@tecleverbidplus`)**

Source (git pull):
```
/home/congo/BidAnalysisPortal/                      ← git root
  bidplus/  gem_portal/  hal_portal/src/  isro_portal/
```
Runtime — `BIDPLUS_RUNTIME_DIR=/home/congo/bidplus-runtime/`:
```
/home/congo/bidplus-runtime/
  venv/   .env   parent.db
  gem/    bids.db  bids/<bid_number>/…              state.json
  hal/    bids.db  bids/<tender_number>_<line>/…    exports/  .browser_profile/
  isro/   bids.db  bids/<tender_id>/…               exports/
```

`bids/<source_pk>/` holds each ≥4 bid's **retained scanned/image files** plus the
**extracted text** (`.txt` per native doc, whose original is then discarded). Source PKs
with `/` (HAL tender numbers) are sanitised to `_` for the path. A **nightly sweep deletes
any entry older than 7 days** (window is config-driven; the ~14 GB working set fits the
deploy box's **~100 GB root LV**, so no disk-high-watermark is needed — reliable execution
of the 7-day sweep is what matters);
a crash-safe pass also reaps obvious orphans. This is the **only** place documents live —
there is no permanent archive.

**Machine-specific conditions (document storage):**
- **Mac (dev):** the iCloud-avoidance rule + the fail-loud guard apply here — the runtime
  root must sit outside `~/Documents`/`~/Desktop`. Disk is roomy; dev mostly runs small
  test batches.
- **Ubuntu (deploy):** no iCloud, so the guard is a no-op and any path outside the repo is
  safe. This box is **constrained on CPU/RAM** (i3, 7.6 GB); storage is **~100 GB on the
  root LV today** (828 GB unallocated in `ubuntu-vg`, extendable via `lvextend` at deploy
  time — see `DEPLOY_WORKFLOW.md` §2). The ~14 GB working set fits 100 GB comfortably, so
  retained-document storage is a non-issue — the only requirement is that the **strict 7-day
  sweep runs reliably** (no disk-high-watermark needed).

**Why (runtime outside iCloud):** an in-tree venv under `~/Documents` is synced by iCloud's
Desktop & Documents feature — thousands of churny files and a real risk of a corrupted
environment. `.gitignore` does **not** stop iCloud. Two acceptable Mac placements for the
runtime root:

1. **Dedicated dir outside Documents/Desktop** — e.g. `~/bidplus-runtime/` *(preferred — cleanest)*.
2. **`.nosync` suffix in-tree** — e.g. `bidplus/.runtime.nosync/` *(iCloud ignores any name ending in `.nosync`; keeps it co-located)*.

**Tool DBs are the critical case (do NOT leave them in-tree).** Today each sample
`config.py` hardcodes `data/bids.db` relative to its tool folder — i.e. inside iCloud.
Fix: make each tool's DB/`downloads`/`exports`/profile paths **env-overridable** and have
its adapter point them at `$BIDPLUS_RUNTIME_DIR/<portal>/`. This is a small, surgical edit
to the sample config (adapting, not rewriting) and **preserves standalone runs** — if
`BIDPLUS_RUNTIME_DIR` is unset, the tool falls back to its in-tree default. A relocated/
symlinked `data/` (`.nosync`) is an acceptable alternative, but the env-override is cleaner
and is what the merge and manual runs should both rely on.

**Already safe automatically:** Playwright browser binaries default to
`~/Library/Caches/ms-playwright/`, which iCloud does not sync — no action needed for those.

**Fail-loud guard:** `config.py` **refuses to start** if the resolved `BIDPLUS_RUNTIME_DIR`
is under `~/Documents` or `~/Desktop`, or contains `Library/Mobile Documents` (iCloud's
backing store). Turns the S0 manual check into an enforced invariant.

**Repo boundary:** the git repo root is **`BidAnalysisPortal/`** — it contains the new
`bidplus/` **and** the three sample tool folders (`gem_portal/`, `hal_portal/src/`,
`isro_portal/`), because the server needs the tool code to run the scrapers. It is **not
git-initialised yet** — S0 does `git init` and adds a `.gitignore` excluding every `*.db`,
`*-wal`, `*-shm`, `exports/`, `downloads/`, `.browser_profile/`, `.env`, and any
`*.nosync`. (Sample `bids.db` fixtures, if you want them tracked for dev, must be
force-added explicitly — but they are **dev reference only, not seeded into the runtime DB**;
the adapters scrape fresh (a full HAL/ISRO/GeM fetch is cheap). Note: there is **no `bids/`
entry** — the runtime document-staging dir `bids/<source_pk>/` lives only under
`$BIDPLUS_RUNTIME_DIR`, outside the git tree, so it never needs ignoring; an unanchored
`bids/` pattern would also risk masking a future in-tree dir of that name.)

**Config contract:** `config.py` reads `BIDPLUS_RUNTIME_DIR` (with a sane default per OS),
and **all** writable paths (venv excepted, created by the setup script) hang off it. No
writable path is ever hardcoded inside the source tree.

---

## 5c. Boilerplate / extraction side-quest (parallel, non-blocking)

Independently of S0–S6, **review real document samples from all three portals** to catalogue
what the summary prompt should **discard vs keep**:

- **Discard:** non-English text (CID/Devanagari artifacts, regional-language blocks),
  generic boilerplate — integrity pacts, debarment undertakings, standard compliance
  annexures, PBG/IP formats, signature blocks, blank pages, page headers/footers.
- **Keep:** **project-specific** terms & conditions, scope, BOQ, technical specs, and —
  critically — **any clause that restricts participation** (mandated hardware, named
  tools/technologies, vendor-tied licenses).

Output of the side-quest = (a) refinements to the Sonnet extraction prompt, and (b)
per-portal **skip-lists** (HAL already has `is_boilerplate_document`; GeM ranks spec
links). This does not block the build; it tunes quality and reduces tokens.

---

## 6. Build slices (S0–S6)

> **Slice-size principle:** *granularity is inversely proportional to how proven the code is.*
> Slices that **wrap tested code** → review by **running**. Slices that introduce **new
> data-mutating logic** → review by **inspect + run** against the DONE-WHEN.

### S0 · Scaffold — *new, structural (front-loads Playwright + runtime layout + repo)*
**Do:** `git init` at repo root `BidAnalysisPortal/` (covers `bidplus/` + the three tool folders) with a `.gitignore` excluding `*.db`/`*-wal`/`*-shm`/`exports/`/`downloads/`/`.browser_profile/`/`.env`/`*.nosync` (no `bids/` entry — staging is out-of-tree under `$BIDPLUS_RUNTIME_DIR`); create `bidplus/` layout; establish `BIDPLUS_RUNTIME_DIR` **outside iCloud** (Mac `~/bidplus-runtime/`, Ubuntu `/home/congo/bidplus-runtime/`) and create the **venv inside it** + install merged `requirements`; write `config.py` (reads `BIDPLUS_RUNTIME_DIR`, resolves all writable paths under it incl. each portal's `bids/<source_pk>/` staging, **fails loud** if it points inside `~/Documents`/`~/Desktop`/`Mobile Documents`, model IDs incl. summary model, tiered gate, summary retry cap (`SUMMARY_MAX_ATTEMPTS`, default 3) + token budget, key from env); make each tool's `config.py` DB/`downloads`/`exports`/profile paths **env-overridable** so they resolve under `$BIDPLUS_RUNTIME_DIR/<portal>/`; place the **single** `.env` in the runtime dir; define the `PortalAdapter` protocol (stub); add `AGENTS.md` + thin `CLAUDE.md` + Cursor rule; run `playwright install-deps` and prove headless Chromium works **on the dev Mac**. *(Disk is a non-issue — the ~14 GB working set fits the deploy box's ~100 GB root LV; just ensure the strict 7-day sweep gets wired at S6. The deploy box itself is a **deploy-phase dependency** — its bring-up, including proving headless Chromium **on the box**, lives in `DEPLOY_WORKFLOW.md` §2, not here.)*
**DONE WHEN:** repo is git-initialised and `git status` shows **no** `*.db`/`.env`/`downloads`/`bids`/`exports`/profile artifacts; venv lives in `$BIDPLUS_RUNTIME_DIR` (confirmed **not** under `~/Documents`/`~/Desktop` on the Mac) and installs cleanly **on the dev Mac** (clean install on the box is verified at deploy time — `DEPLOY_WORKFLOW.md` §2); **each tool, run manually, writes its `bids.db` + `bids/<source_pk>/` staging under `$BIDPLUS_RUNTIME_DIR/<portal>/` — nothing writable lands in the synced tree**; `config.py` aborts with a clear error if `BIDPLUS_RUNTIME_DIR` resolves inside iCloud (Mac); a trivial headless-Chromium script succeeds **on the dev Mac** (box-side proof deferred to deploy provisioning); `config` loads the single `ANTHROPIC_API_KEY` from env; `PortalAdapter` defined (no impls yet); guardrail files present.

### S1 · HAL behind the orchestrator — *wrap tested code; biggest risk, done first*
**Do:** implement the HAL adapter wrapping its existing scrape → Pass 1 → own-`bids.db` pipeline; minimal parent launcher runs HAL headless; wire the unified rubric + the dry-run/explain view. **Start from an empty runtime DB** — the bundled 143-tender fixture is **dev reference only, not seeded**; a fresh HAL full-scrape is cheap. The runtime `bids.db` then **persists across runs** so lifecycle (EXTENDED/`first_seen`) works.
**DONE WHEN:** launcher completes a **headless** HAL scrape on the box; HAL's own `bids.db` populates with tenders (count > 0, sane fields); Pass 1 runs under the unified rubric and **parses cleanly** (incl. `RECOMMENDATION`); the dry-run view prints *input fields → prompt → parsed result* for one tender; no crash; logs captured.

### S2 · ISRO + GeM behind the orchestrator — *wrap tested code; light*
**Do:** implement ISRO then GeM adapters (pure HTTP); confirm strict sequential execution in the parent launcher. (ISRO's parser now expects the full unified-rubric output shape.)
**DONE WHEN:** launcher runs **HAL → ISRO → GeM one at a time** (verified by timestamps/logs — never parallel); each populates its own `bids.db`; Pass 1 parses under the unified rubric for all three; dry-run view works per portal.

### S3 · Parent merge — *NEW; real review (your DB-compare lands here)*
**Do:** create the parent DB with `gem_bids`/`hal_bids`/`isro_bids` (each mirroring its tool schema + overlay columns, defaulted) + shared `users`/`scrape_runs`; implement gap-aware **full-reconciliation upsert** from each tool DB → its parent table. The upsert **mirrors tool-owned fields** (including `bid_status`/`extension_count`/`closing_date`, so an EXTENDED bid's flag + closing date update naturally) and **never overwrites any overlay column** (AI-derived or human) — an extended bid is **not** re-summarized.
**DONE WHEN:** after a portal run, that portal's parent table **mirrors its tool `bids.db`** for all synced fields (download-and-compare: row counts + values match); running the merge **twice yields zero changes** the second time (idempotent); a simulated overlay/human edit (e.g. `user_state`) **is not overwritten** by a re-merge; a simulated **EXTENDED** re-issue of an already-summarized row (bump `extension_count` / push `closing_date` later in the tool DB) **updates only `bid_status`/`extension_count`/`closing_date` and leaves every overlay column — `docs_summarized`, `summary_json`, `user_state` — untouched** (no re-summarize, no reset); rows added by a **manual** tool run are picked up on the next merge.

### S4 · Orchestrator hardening + run logging — *NEW; real review*
**Do:** enforce sequential order; **INSERT an in-progress `scrape_runs` row at run start** (`status='running'`, `finished_at` NULL) and finalize it at the end; write per-tool + overall rows (status, counts, error, **per-stage durations**); on a failed/partial cycle **raise a sticky `system_alerts` row** (cleared only by a human, never by a later success); compute the **tiered gate** (score 5 → auto-Sonnet queue **= score 5 AND `docs_summarized=0` AND `summary_status IS NULL`** — already-done and previously-`failed` bids are excluded so they aren't re-burned nightly; score 4 → local-extract queue; score 3 → none; **CLOSED → excluded from all queues**); install the systemd timer (~3am).
**DONE WHEN:** a full cycle writes 1 overall + 3 per-tool `scrape_runs` rows with correct counts **and stage timings**; an **in-progress row exists during the run** (`finished_at IS NULL`) and is finalized after; a deliberately failed portal yields `status=failed` for it, `partial` overall, **and the other portals still finish**; that failure **raises a `system_alerts` row**, and a **subsequent fully-successful cycle leaves that alert active** (`cleared_at` still NULL — proving it's sticky, not last-run-status); bids are bucketed **5 vs 4 vs 3** correctly **and CLOSED bids are excluded**; the timer fires the cycle on schedule.

### S5 · Document fetch + local extraction + summarize module — *NEW; real review (replaces the old vector slices)*
**Do:** build the **standalone, score-agnostic Sonnet summarization module** (§8b / #24) — the single path to Sonnet — and wire S5 to run it overnight for score 5. The module, given a bid: (1) ensures its documents are **saved locally** in `$BIDPLUS_RUNTIME_DIR/<portal>/bids/<source_pk>/` (fetched via the adapter; **this happens for every score, score 5 included**); (2) **extracts text** from text-based docs (pdfplumber/python-docx/openpyxl + regex for specific fields), stores it (`.txt`); (3) **retains non-text files** (scanned/image) in the bid dir; (4) sends **extracted text + non-text files (document/image blocks)** to **Sonnet 4.6** with the structured-extraction prompt (discards non-English + generic boilerplate, keeps project-specific T&C); (5) **validates the response with Pydantic** (**bounded retry — default 3 attempts — feeding back validation errors; on exhaustion sets `summary_status='failed'`, logs it, flags for manual review, and does NOT store/queue further**), then on success writes `summary_json` (project, deliverables, deliverable+submission timelines, total value, EMD, vendor qualification, client constraints, **restrictive-eligibility clauses**) + `summary_model` + `summary_generated_at`, sets `docs_summarized=1`, `summary_status='ok'`, `has_restrictive_eligibility`. **Trigger by score (this slice):** **score 5** → run the module **now**; **score 4** → instead store only a cheap **regex preview** (`local_extract_json`, `local_extracted=1`, eligibility pre-flag) and **stop** — the module is invoked later by the web-app "Fetch more" click. **Files are NOT deleted here** — they age out via the 7-day sweep (S6).
**DONE WHEN:** a **score-5** bid has its documents **saved locally**, then is summarized end-to-end into **Pydantic-validated** JSON covering **all** fields, including a **scanned/image** doc read via Sonnet vision (**no local OCR**); a malformed Sonnet response is **caught and retried up to the cap**, never stored raw — and a **persistently** malformed bid (cap exhausted) is marked `summary_status='failed'`, **logged** (`summary_failed_count`++), left `docs_summarized=0`, and **not re-queued** on the next run; a **score-4** bid has `local_extract_json` populated + files staged in its bid dir and **no Sonnet call made**; invoking the **module** on that score-4 bid (simulating a click) produces `summary_json` **from the stored files without re-fetch**; a **GeM** bid pulls the primary PDF **plus its linked supporting docs**; a bid with a **restrictive clause** is flagged (`has_restrictive_eligibility=1`); paths resolve under `$BIDPLUS_RUNTIME_DIR/<portal>/bids/<source_pk>/` on **both machines**; re-running does **not** reprocess an already-done unchanged bid (idempotent); an **oversized** bundle is summarized from the **primary tender doc(s) only**, stored with `summary_coverage='partial'` and **flagged for manual review** (no map-reduce); work + timing respect the overnight budget.

### S6 · Lifecycle + retention sweep + nightly budget — *NEW; real review (replaces the old purge slice)*
**Do:** implement the CLOSED sweep (mark past-closing bids CLOSED, **retain** the parent row + its data); implement the **strict 7-day file-retention sweep** over `$BIDPLUS_RUNTIME_DIR/<portal>/bids/` (config-driven window; ~14 GB working set fits the ~100 GB root LV, so no high-watermark needed), plus crash-safe reaping of obvious orphans; assert the full cycle fits the overnight window using the per-stage timings from S4.
**DONE WHEN:** marking a bid CLOSED **retains** its parent row + `summary_json`/`local_extract_json` but removes any residual files; the nightly sweep marks **all** past-closing bids CLOSED; **files older than 7 days are deleted while newer ones are kept** (a bid clicked within the window still has its files); **no orphaned dirs** remain under any `<portal>/bids/`; the sweep runs correctly on **both machines** (Mac dev + Ubuntu deploy); a representative full cycle's per-stage durations are in `scrape_runs` and complete **before the configured ~9am deadline**.

---

## 7. Parent DB schema (sketch)

Each portal table mirrors its tool's columns; only the **overlay** block and `last_synced_at` are added. Example for HAL (others analogous, keyed by their own PKs):

```sql
CREATE TABLE hal_bids (
    -- mirror of the HAL tool schema (composite PK)
    tender_number TEXT NOT NULL,
    line_number   TEXT NOT NULL,
    buyer TEXT, tender_description TEXT, tender_region TEXT,
    estimated_cost TEXT, emd_listing TEXT, closing_date TEXT, bidder_type TEXT,
    pass1_score INTEGER, pass1_confidence TEXT, pass1_domain TEXT,
    pass1_rationale TEXT, pass1_gaps TEXT,
    bid_status TEXT, extension_count INTEGER, first_seen_date TEXT,
    -- overlay columns (parent-owned). The merge NEVER overwrites these — AI-derived
    --   (local_extracted, local_extract_json, docs_summarized, summary_json, summary_model,
    --    summary_generated_at, has_restrictive_eligibility, summary_coverage,
    --    summary_status) or human (user_state, disposed_by, disposed_at). Each is written
    --   once. EXTENDED touches only the mirrored tool fields (bid_status / extension_count /
    --   closing_date); it does NOT re-summarize or reset overlay.
    local_extracted             INTEGER DEFAULT 0,   -- 1 once local regex/heuristic extraction ran
    local_extract_json          TEXT,                -- score-4 preview fields (EMD/value/dates/...)
    docs_summarized             INTEGER DEFAULT 0,   -- 1 once a VALID Sonnet summary is stored
    summary_status              TEXT,                -- NULL=not attempted | 'ok' | 'failed' (retries exhausted → manual review, NOT auto-re-queued)
    summary_json                TEXT,                -- structured Sonnet extraction (shape below)
    summary_model               TEXT,                -- e.g. claude-sonnet-4-6 (provenance)
    summary_generated_at        TEXT,
    summary_coverage            TEXT DEFAULT 'full', -- 'full' | 'partial' (oversized → primary docs only; flag for manual review)
    has_restrictive_eligibility INTEGER DEFAULT 0,   -- UI flag: bid limits who can participate
    user_state                  TEXT DEFAULT 'new',  -- new/viewed/accepted/rejected
    disposed_by                 INTEGER,             -- users.id
    disposed_at                 TEXT,
    last_synced_at              TEXT,
    PRIMARY KEY (tender_number, line_number)
);
-- gem_bids  → PK (bid_number);  isro_bids → PK (tender_id);  same overlay block.

-- summary_json shape (authored at S5; tuned by the §5c side-quest):
--   {
--     "project_description":         "clean EN prose — what the project is",
--     "deliverables":                "clean EN prose — what must be delivered",
--     "deliverable_timeline":        "milestones / delivery schedule",
--     "submission_timeline":         "bid submission / closing schedule",
--     "total_value":                 "contract/estimated value (with currency)",
--     "emd_value":                   "EMD amount",
--     "vendor_qualification":        "eligibility / qualification criteria",
--     "client_constraints":          "client-mandated constraints",
--     "eligibility_restrictions":    ["clauses that limit who can bid — mandated hardware,
--                                      named tools/tech, vendor-tied software licenses"],
--     "has_restrictive_eligibility": true | false,
--     "coverage":                    "full" | "partial"   // 'partial' = oversized bundle,
--                                                          //  primary tender doc(s) only
--   }
-- 'coverage' mirrors into the summary_coverage column; 'partial' bids are flagged for manual review.
-- Produced by the §8b summarization module and VALIDATED with a Pydantic model before write.
-- Extraction DISCARDS non-English text and generic boilerplate; KEEPS project-specific T&C.

CREATE TABLE users (
    id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL, created_at TEXT          -- argon2id/bcrypt
);

CREATE TABLE scrape_runs (
    id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT,  -- in-progress row: finished_at IS NULL
    tool TEXT,                                            -- NULL = overall row
    status TEXT,                                          -- running/success/partial/failed
    new_count INTEGER, updated_count INTEGER, closed_count INTEGER,
    scored_count INTEGER,                                -- Pass 1 scored this run
    local_extracted_count INTEGER,                       -- score-4 bids locally extracted
    summarized_count INTEGER,                            -- score-5 bids Sonnet-summarized
    summary_failed_count INTEGER,                        -- score-5 bids that exhausted retries (summary_status='failed')
    error_summary TEXT,
    stage_timings_json TEXT                               -- per-stage durations (overnight budget)
);
-- The orchestrator INSERTs an in-progress row at run start (status='running', finished_at NULL)
-- and finalizes it at the end. This lets the deploy active-run guard (DEPLOY_WORKFLOW.md §3.1)
-- detect a live run via `finished_at IS NULL`, not a stale terminal status.

CREATE TABLE system_alerts (
    id          INTEGER PRIMARY KEY,
    raised_at   TEXT,            -- when a failed/partial cycle raised this
    run_id      INTEGER,         -- scrape_runs.id that triggered it
    reason      TEXT,            -- short failure summary shown in the banner
    cleared_at  TEXT,            -- NULL = still active (sticky)
    cleared_by  INTEGER          -- users.id who acknowledged it (web-app round)
);
-- STICKY: an alert is raised on any failed/partial cycle and stays active (cleared_at IS NULL)
-- until a human clears it in the web app. A subsequent SUCCESSFUL run does NOT clear it —
-- so a failure three weeks ago is still visible when someone finally opens the app.
```

## 8. `PortalAdapter` interface (sketch)

```python
class PortalAdapter(Protocol):
    portal: str   # 'gem' | 'hal' | 'isro'

    def run_pipeline(self) -> RunResult:
        """Wrap the tool's existing scrape → Pass 1 → own-bids.db flow.
        Returns counts + status for scrape_runs. Reuses the sample code; does not
        re-implement portal transport."""

    def tool_db_path(self) -> str:
        """Path to this tool's own bids.db (merge source), resolved under
        $BIDPLUS_RUNTIME_DIR/<portal>/ — never inside the synced source tree."""

    def fetch_documents(self, source_pk) -> list[FetchedDoc]:
        """Per-portal acquisition into the bid's per-bid dir
        $BIDPLUS_RUNTIME_DIR/<portal>/bids/<sanitised source_pk>/ (resolved by config,
        same structure on Mac dev + Ubuntu deploy): HAL/ISRO enumerate all docs from the
        tender document-view; GeM downloads the one primary PDF, parses it for
        supporting-doc links, then fetches those. Returns a descriptor per DOWNLOADED file:
        FetchedDoc(doc_name, local_path, fmt). The adapter ONLY downloads raw files into the
        bid dir — it does NOT extract text and does NOT decide what goes to Sonnet. Text
        extraction and the text-vs-scan split are owned solely by the §8b summarization
        module (the single, portal-agnostic extractor); the adapter just acquires bytes.
        Files are NOT deleted by the caller — the 7-day retention sweep (S6) owns deletion.
        Used by S5 and, later, the web-app 'Fetch more' (score 4) / on-demand (score 3) paths."""

    def explain(self, source_pk) -> dict:
        """Dry-run view: input fields → assembled prompt → parsed Pass-1 result.
        Powers manual validation."""

# FetchedDoc: a small dataclass (doc_name: str, local_path: str, fmt: str).
#             Raw downloaded file only — no extracted_text field; extraction is the §8b
#             module's job, not the adapter's.
```

## 8b. Summarization module (score-agnostic, portal-agnostic)

The **single path for anything sent to Sonnet** — its own module, separate from the
adapters. One entry point, e.g.:

```python
def summarize_bid(portal: str, source_pk: str) -> BidSummary:  # BidSummary = a Pydantic model
    """1. Ensure the bid's docs are staged in bids/<source_pk>/ (fetch via the adapter if
          absent AND the bid is still open; a CLOSED bid raises/returns nothing).
       2. Extract text from text-based docs (pdfplumber/python-docx/openpyxl + regex fields).
          This module is the SOLE extractor — adapters hand back raw files only. It also
          owns the text-vs-scan decision (text layer present → extract & discard the native
          original; none → treat as scan and retain the file).
       3. Build the Sonnet payload: extracted text + non-text files (scanned/image) as
          document/image blocks. Estimate input tokens; if within the configured budget
          (model input window − headroom) → coverage='full'. If it OVERFLOWS (rare): drop
          secondary annexures, keep only the PRIMARY tender doc(s) (GeM: the primary PDF;
          HAL/ISRO: the main tender/NIT doc) until it fits → coverage='partial'. NO map-reduce.
       4. Call Sonnet 4.6 with the structured-extraction prompt.
       5. Parse + VALIDATE with Pydantic. On a schema failure, retry up to
          SUMMARY_MAX_ATTEMPTS (config; default 3 total = initial + 2 retries), each retry
          feeding the validation errors back as a corrective nudge ("your prior output failed
          validation: <errors>; return valid JSON only"). BOUNDED — never an open loop.
          If still invalid at the cap: do NOT store raw, do NOT set docs_summarized; set
          summary_status='failed', log (bid, portal, attempts, last error) to scrape_runs
          (summary_failed_count++) and flag for manual review — the bid is NOT auto-re-queued
          on later runs (auto queue = score 5 AND docs_summarized=0 AND summary_status IS NULL
          AND not CLOSED). A human can force a retry from the web-app (clears summary_status).
       6. On success: persist summary_json + summary_model + summary_generated_at
          + has_restrictive_eligibility + summary_coverage; set docs_summarized=1,
          summary_status='ok'. A 'partial' bid is flagged for manual review. Return the
          validated BidSummary.
    """
```

Same module for **every** score — only the trigger differs (#1): auto@5 (S5), on-click@4
and on-demand@≤3 (web-app round). Idempotent (skips a bid with `docs_summarized=1`); **no automatic re-summarize** — EXTENDED only updates the flag + closing date (§7 / merge invariant), it never re-runs the module or resets overlay.

---

## 9. Deferred to the web-app round (not now)
- **API contract** (endpoint shapes, session auth) — design when web-app build starts.
- **The summarization-module triggers** — invoke the **S5 module** (§8b) for **score-4** bids on a "Fetch more" click (on the already-staged files; re-fetch only if the 7-day window has lapsed), **score-3** bids on demand (fetch + module), and **score 2/1/0** only if the user **explicitly forces** it. **A CLOSED bid does nothing — no fetch, no AI.** Behind a single global lock; accept/reject + forced disposition.
- **The web-app *interface*** (portal-segmented list, local-extract preview vs full summary, runs/logs view) — may be decided earlier in parallel; it does not block S0–S6.
- *(No longer deferred: the structured summary shape + extraction prompt + the **summarization module** itself (incl. Pydantic validation) — built at S5, tuned by the §5c side-quest. The web-app round only adds the user-facing trigger.)*

**Explicit non-goals (deploy-once cadence — do NOT build):** automated per-lane smoke harnesses, `--dry-run`/fixture modes for the scrapers, and a stubbed/recorded-Sonnet smoke path. The system is deployed once and revisited only on a major issue (e.g. a portal changes its markup), so a CI-style smoke suite is poor ROI. Post-deploy verification is **manual**: redeploy → run once → eyeball `scrape_runs` + a sample result (see `DEPLOY_WORKFLOW.md`).

---

## Appendix A — `AGENTS.md` source (already extracted to repo-root `AGENTS.md`)

> This has been lifted into the live **repo-root `AGENTS.md`** (alongside `CLAUDE.md` and
> `.cursor/rules/main.mdc`) so Claude Code and Cursor auto-load it every turn. Keep the
> two in sync; the copy below is the reference. (Repo root, not `bidplus/`, is where both
> tools look — consistent with the §5b source tree.)

```markdown
# AGENTS.md — Teclever Bid Portal (backend)

## What this is
A parent orchestrator that runs three existing portal scrapers (HAL, ISRO, GeM)
sequentially, merges their SQLite data into a parent SQLite (one table per portal),
Pass-1-scores every bid against a unified rubric, and for every bid scoring >= 4 fetches
its documents into a per-bid dir and SAVES THEM LOCALLY (every score). A single
score-agnostic summarization MODULE (extract text -> send text + non-text files to Sonnet
4.6 -> validate with Pydantic -> store) is the only path to Sonnet. It is TRIGGERED by
score: 5 -> run overnight; 4 -> cheap regex preview now, module DEFERRED to a "Fetch more"
click; 3 -> on demand; 2/1/0 -> only if the user forces it. There is NO vector database and
NO local OCR. Downloaded files are staged, not hoarded — a strict nightly 7-day sweep deletes
them. The web app is a later, separate effort.

## The samples are known-good
`gem_portal/`, `hal_portal/src/`, `isro_portal/` are FULLY FUNCTIONAL. Reuse and adapt
their scrape / download / Pass-1 / DB-write logic. Do NOT rewrite portal transport.

## Golden rules (do not break)
- Touch portals only through `PortalAdapter`. Never re-implement `fetcher.py`,
  HAL `session.py`, or GeM `csrf_handler.py`.
- Scraping is STRICTLY SEQUENTIAL (HAL -> ISRO -> GeM). One heavy op at a time.
- Parent merge is ALWAYS upsert. NEVER overwrite ANY overlay column — AI-derived
  (docs_summarized, summary_json/model/at, summary_coverage, local_extracted,
  local_extract_json, has_restrictive_eligibility) or human (user_state, disposed_by,
  disposed_at). The merge
  mirrors tool-owned fields only. EXTENDED updates just bid_status/extension_count/closing_date
  and does NOT re-summarize or reset overlay — a bid is summarized at most once.
- NO vector store, NO embeddings, NO local OCR. Sonnet reads docs (incl. scans/images)
  natively. Do not reintroduce ChromaDB or an embedding model.
- Documents are SAVED LOCALLY for every fetched bid (score 5 included) and text-extracted
  BEFORE anything goes to Sonnet.
- ONE PATH TO SONNET: all summarization goes through the single §8b module (extract text ->
  text + non-text files -> Sonnet -> Pydantic-validate -> store). Never store an
  unvalidated/malformed result. Validation retry is BOUNDED (default 3 attempts); on
  exhaustion set summary_status='failed', log it, flag for manual review, and do NOT
  auto-re-queue the bid — never an open loop. No other code path calls Sonnet for documents.
- Score tiering is TRIGGER-ONLY (same module for all scores): SCORE 5 IS THE ONLY AUTOMATIC
  Sonnet call. SCORES 4 AND BELOW must NOT be sent to Sonnet without EXPLICIT USER
  CONFIRMATION — score 4 shows a regex preview + runs the module on a "Fetch more" click;
  score 3/2/1/0 run the module on demand.
- Documents are STAGED, NOT HOARDED. Files (any format: PDF, scanned/image, Word, Excel)
  download into $BIDPLUS_RUNTIME_DIR/<portal>/bids/<source_pk>/. Native-text files: extract
  text, store it, DISCARD the source file. Scanned/image files: KEEP them for Sonnet. A
  nightly 7-day sweep is the deletion mechanism (NOT per-bid immediate delete). The DB
  (local extraction + Sonnet summary) is the durable artifact.
- Document acquisition is per-portal: HAL/ISRO enumerate all docs from the document-view;
  GeM downloads ONE primary PDF and parses it for links to supporting docs, then fetches
  those. The adapter owns this difference.
- The summary prompt DISCARDS non-English text and generic boilerplate but KEEPS
  project-specific T&C, and ALWAYS surfaces restrictive participation clauses (mandated
  hardware, named tools, vendor-tied licenses) in their own field + has_restrictive_eligibility.
- Summarize via Sonnet once per bid (idempotent on docs_summarized=1). NO automatic
  re-summarize — EXTENDED only updates flag + closing date; re-running the module is a no-op.
- CLOSED is terminal — NEVER fetch documents, run local extraction, or summarize a CLOSED
  bid (gate skips it; a later "Fetch more" click on a CLOSED bid does nothing).
- ONE ANTHROPIC_API_KEY, from env only (orchestrator injects it for all adapters). Do NOT
  create per-tool .env files.
- Build slices S0..S6 IN ORDER. Do not start a slice until the prior DONE-WHEN passes.
- Always expose a dry-run/explain view (input fields -> prompt -> parsed result).
- Runtime state lives OUTSIDE the source tree, under $BIDPLUS_RUNTIME_DIR (venv, parent.db,
  .env, and per-portal <portal>/ dirs holding each tool's bids.db, the bids/<source_pk>/
  document staging, exports, .browser_profile). On the Mac this MUST be outside iCloud
  (~/Documents, ~/Desktop); on the Ubuntu deploy box there is no iCloud so any path outside
  the repo is fine. This INCLUDES the tool bids.db files — make each tool config.py
  env-overridable so its data resolves under $BIDPLUS_RUNTIME_DIR/<portal>/ (falls back to
  in-tree default only when unset). A live SQLite syncing mid-write WILL corrupt it.
- config.py must FAIL LOUD if $BIDPLUS_RUNTIME_DIR is inside ~/Documents, ~/Desktop, or
  Mobile Documents (Mac guard; no-op on Ubuntu). No writable path is hardcoded in source.
- Git root is BidAnalysisPortal/ (bidplus/ + the three tool folders). .gitignore excludes
  *.db, *-wal, *-shm, exports/, downloads/, .browser_profile/, .env, *.nosync. (No bids/
  entry: the bids/<pk>/ staging lives under $BIDPLUS_RUNTIME_DIR, outside the tree.)

## Unified rubric + summary
All portals use the one detailed `capability_reference.md` for Pass 1. ISRO re-scores
under it; its Pass-1 parser must accept the full output shape (MATCHING TECH,
RECOMMENDATION). The Sonnet summary uses a SEPARATE structured-extraction prompt (the
"second rubric") — see summary_json shape in the plan.

## Overnight budget
The cycle starts ~3am and must finish by ~9am. Log per-stage durations to scrape_runs.
Expected >=4 (docs-bearing) volume is tens/night (~30-40), not hundreds.

## Pins
Python 3.12 · one venv · Pass-1 model claude-haiku-4-5-20251001 ·
Summary model claude-sonnet-4-6 (output Pydantic-validated) · SQLite WAL · systemd timer.

## How to run a tool manually
Each tool still runs standalone from its own folder (see its README). FIRST export
BIDPLUS_RUNTIME_DIR so its bids.db lands outside iCloud; otherwise it falls back to the
in-tree default (which is iCloud-synced — avoid). The next merge reconciles new rows.

## Environments
Develop on the Mac: git root ~/Documents/Projects/AI/BidAnalysisPortal/ (new code under
bidplus/), iCloud-backed. Deploy on the Ubuntu server congo@tecleverbidplus: git pull to
/home/congo/BidAnalysisPortal/. Set BIDPLUS_RUNTIME_DIR per machine: Mac ~/bidplus-runtime,
Ubuntu /home/congo/bidplus-runtime. Runtime structure is identical on both; only the root
differs. The deploy box's ~100 GB root LV easily holds the ~14 GB working set, so
retained-doc storage is a non-issue — just ensure the strict 7-day sweep runs reliably (no
disk-high-watermark needed). Deploy-box provisioning, SSH deploy, and remote smoke-testing
are specified standalone in `DEPLOY_WORKFLOW.md`.

## Validation
Per-slice MANUAL validation: run it, eyeball the dry-run view, and for the merge,
compare the tool's bids.db against the parent table. Automated tests are deferred.
```

## Appendix B — Slice review cheat-sheet

| Slice | Type | How you review |
|-------|------|----------------|
| S0 Scaffold | new/structural | git clean of artifacts; venv outside iCloud; tool DBs land in runtime dir; headless Chromium runs |
| S1 HAL | wrap tested | run it; dry-run view; bids.db populates |
| S2 ISRO+GeM | wrap tested | run each; sequential confirmed |
| S3 Parent merge | **new/mutating** | **DB compare; double-run idempotent; overlay never clobbered (AI + human); EXTENDED mirrors flag/closing-date only** |
| S4 Orchestrator | **new/mutating** | scrape_runs rows + stage timings; induced-failure isolation; tiered gate (5/4/3) |
| S5 Fetch + extract + summarize module | **new/mutating** | docs saved locally (all scores); native→text, scans retained; §8b module = extract→Sonnet→Pydantic→store; malformed: bounded retry (default 3) then `summary_status='failed'`+logged, not stored; score-4 regex-only (no Sonnet); score-5 summarized; GeM link-following; vision on scans; eligibility flag; idempotent; both machines |
| S6 Lifecycle + retention + budget | **new/mutating** | CLOSED retains row+data; 7-day sweep deletes >7d keeps newer; no orphan dirs; runs on both machines; cycle fits overnight window |

---

## Appendix C — Slice Summary Table & Handoff Matrix (S0–S6)

> Mirrors `Slice_Summary_and_Handoff_Matrix.xlsx`. Derived from each slice's Do / DONE-WHEN / invariants.

### C.1 Slice Summary Table

| Slice | What it builds | Pre-condition (needs from prior) | What it writes/creates | Key invariants the agent must respect | Manual validation (from DONE-WHEN) |
|---|---|---|---|---|---|
| **S0 · Scaffold** | • Repo + `bidplus/` layout<br>• venv in `$BIDPLUS_RUNTIME_DIR` (outside iCloud)<br>• `config.py`: runtime paths, model IDs, tiered-gate const, key from env, fail-loud guard<br>• Tool `config.py` env-overridable<br>• Single `.env` in runtime dir<br>• `PortalAdapter` protocol stub<br>• `AGENTS.md` / `CLAUDE.md` / Cursor rule<br>• Playwright install-deps + headless Chromium proof | • Greenfield (no prior slice)<br>• The 3 sample tool folders exist | • `git init` at `BidAnalysisPortal/` + `.gitignore`<br>• `$BIDPLUS_RUNTIME_DIR/{venv, .env}`<br>• `config.py` + guardrail files<br>• `PortalAdapter` protocol definition | • Runtime outside iCloud (Mac)<br>• `config.py` fails loud if runtime inside iCloud<br>• One venv, one `.env` / one key<br>• No writable state in synced tree<br>• Git root = `BidAnalysisPortal/` | • `git status` clean of `*.db`/`.env`/`downloads`/`bids`/`exports`<br>• venv not under `~/Documents` or `~/Desktop`; installs cleanly on dev Mac (box install deferred to deploy)<br>• Each tool writes `bids.db` + `bids/<pk>/` under runtime dir<br>• `config.py` aborts if runtime inside iCloud<br>• Headless Chromium prints a page title on the dev Mac (box-side proof at deploy time)<br>• Key loads from env<br>• `PortalAdapter` defined; guardrail files present |
| **S1 · HAL adapter** | • HAL adapter (wraps scrape → Pass 1 → own `bids.db`)<br>• Minimal parent launcher (HAL headless)<br>• Unified rubric wired<br>• Dry-run / explain view<br>• Starts from an empty runtime DB (no fixture seed) | • S0: config, `PortalAdapter` protocol, venv, runtime dir, Playwright working | • Runtime `hal/bids.db` populated<br>• HAL adapter implementation<br>• Parent launcher + logs | • Touch portals only via the adapter (don't reimplement `session.py` / `fetcher.py`)<br>• Reuse the samples<br>• Key from env<br>• Headless<br>• Expose the dry-run / explain view | • Headless HAL scrape completes on the box<br>• `hal/bids.db` count > 0, sane fields<br>• Pass 1 parses under unified rubric incl. `RECOMMENDATION`<br>• Dry-run prints input → prompt → parsed for one tender<br>• No crash; logs captured |
| **S2 · ISRO + GeM adapters** | • ISRO then GeM adapters (HTTP)<br>• Strict sequential execution in the launcher<br>• ISRO parser moved to full unified-rubric output shape | • S1: launcher exists; adapter pattern proven; unified rubric | • Runtime `isro/bids.db` + `gem/bids.db` populated<br>• 2 adapter implementations | • Strictly sequential HAL → ISRO → GeM (never parallel)<br>• One heavy op at a time<br>• Adapter-only<br>• GeM TLS / certifi note<br>• ISRO re-scores under the detailed rubric | • Launcher runs the 3 one at a time (timestamps/logs; never parallel)<br>• Each populates its own `bids.db`<br>• Pass 1 parses under unified rubric for all three<br>• Dry-run works per portal |
| **S3 · Parent merge** | • Parent DB: `gem_bids`/`hal_bids`/`isro_bids` mirroring tool schema + overlay cols defaulted; `users`; `scrape_runs`<br>• Gap-aware full-reconciliation upsert: tool DB → parent table | • S2: 3 tool DBs populate; sequential run works | • `parent.db` with per-portal tables + `users` + `scrape_runs`<br>• Overlay columns | • Merge is always UPSERT<br>• Never overwrite any overlay column (AI-derived or human)<br>• EXTENDED updates only mirrored `bid_status`/`extension_count`/`closing_date` (no re-summarize, no reset)<br>• Gap-aware reconciliation<br>• Idempotent | • Parent table mirrors tool `bids.db` (row counts + values match; download-and-compare)<br>• Double-run merge = zero changes<br>• Simulated `user_state` edit not overwritten<br>• Simulated EXTENDED re-issue updates `bid_status`/`closing_date` only; overlay (`docs_summarized`/`summary_json`/`user_state`) untouched<br>• Rows from a manual tool run picked up on next merge |
| **S4 · Orchestrator + run logging** | • Enforce sequential order<br>• Write `scrape_runs` (overall + per-tool: status/counts/error/stage timings)<br>• Tiered gate: 5 → auto-Sonnet queue; 4 → regex-preview queue; 3 → none; CLOSED excluded<br>• systemd timer (~3am) | • S3: merge works; `scrape_runs` + per-portal tables exist | • 1 overall + 3 per-tool `scrape_runs` rows w/ counts + `stage_timings_json`<br>• systemd timer unit<br>• Gate buckets (queues) | • Strictly sequential<br>• Failure isolation (one portal fails → others finish)<br>• CLOSED excluded from the gate<br>• Overnight budget logged<br>• Gate only buckets (no auto-Sonnet for ≤4) | • Full cycle writes 1 + 3 `scrape_runs` with correct counts + timings<br>• A deliberately failed portal → failed for it, partial overall, others finish<br>• Bids bucketed 5 vs 4 vs 3 correctly and CLOSED excluded<br>• Timer fires on schedule |
| **S5 · Fetch + local extract + §8b module** | • §8b score-agnostic summarization module: save docs locally → extract text → text+non-text → Sonnet 4.6 → Pydantic-validate → store<br>• Auto-run the module for score 5<br>• Score 4 = regex preview only (stop; no Sonnet)<br>• CLOSED skipped | • S4: tiered queues; CLOSED excluded<br>• `adapter.fetch_documents` (from S1/S2)<br>• Parent overlay cols (from S3) | • `bids/<source_pk>/` (saved docs: `.txt` + retained scans)<br>• Score 4: `local_extract_json`, `local_extracted`<br>• Score 5: `summary_json`, `summary_model`, `summary_generated_at`, `docs_summarized`, `summary_status`, `has_restrictive_eligibility`, `summary_coverage`<br>• Pydantic models | • Docs saved locally for every score<br>• One path to Sonnet (Pydantic-validated; never store malformed)<br>• Score 5 only auto; 4 and below need explicit user confirmation<br>• Non-CLOSED only<br>• Files not deleted here (S6 owns deletion)<br>• Per-portal acquisition (GeM link-following)<br>• Eligibility surfaced; idempotent | • Score-5 bid: docs saved locally, then Pydantic-validated JSON covering all fields, incl. a scanned doc via vision<br>• Malformed Sonnet response retried to the cap, never stored raw; persistently-malformed bid → `summary_status='failed'` + logged + not re-queued<br>• Score-4 bid: `local_extract_json` + staged files + no Sonnet call<br>• Invoking the module on it (sim click) → `summary_json` from stored files, no re-fetch<br>• GeM pulls primary + linked docs<br>• Restrictive clause flagged<br>• Paths under runtime on both machines<br>• Idempotent; oversized → primary-doc-only (`coverage='partial'` + manual-review flag); within budget |
| **S6 · Lifecycle + retention sweep** | • CLOSED sweep (mark past-closing CLOSED; retain row + data)<br>• Strict 7-day file-retention sweep over `bids/`<br>• Crash-safe orphan reaping<br>• Assert cycle fits overnight window via S4 timings | • S5: `bids/<pk>/` dirs + staged files; summaries/previews in DB; S4 stage timings | • `bid_status=CLOSED` transitions<br>• Deletes files > 7 days from `bids/`<br>• Retains parent rows + `summary_json` / `local_extract_json` | • CLOSED terminal (retain row + data; remove files)<br>• Strict 7-day sweep is the deletion mechanism (~14 GB working set fits ~100 GB root LV; no watermark)<br>• No orphan dirs<br>• Runs on both machines<br>• Cycle before ~9am | • CLOSED retains row + `summary_json`/`local_extract_json` but removes residual files<br>• Nightly sweep marks all past-closing bids CLOSED<br>• Files > 7 days deleted, newer kept (clicked-within-window still has files)<br>• No orphan dirs under `<portal>/bids/`<br>• Sweep runs on both machines<br>• Per-stage durations in `scrape_runs`; completes before ~9am |

### C.2 Handoff Matrix (producer → consumer)

| Transition | Producer leaves (artifact / state) | Consumer expects to find |
|---|---|---|
| **S0 → S1** | • `config.py` (runtime-path resolver, model IDs, tiered-gate const, key-from-env, fail-loud guard)<br>• `$BIDPLUS_RUNTIME_DIR/{venv, .env}`<br>• `PortalAdapter` protocol (stub, no impls)<br>• Tool `config.py` env-overridable<br>• Working headless Chromium<br>• Git repo + `.gitignore` | • A defined `PortalAdapter` protocol to implement HAL against<br>• `config` to resolve `hal/` runtime paths + key + model IDs<br>• venv with deps (incl. Playwright)<br>• The `hal_portal/src` sample to wrap |
| **S1 → S2** | • HAL adapter implementing the full protocol (`run_pipeline` / `tool_db_path` / `fetch_documents` / `explain`)<br>• Minimal parent launcher<br>• Unified rubric wired<br>• Dry-run / explain harness<br>• `hal/bids.db` populated | • The parent launcher to extend with 2 more adapters<br>• The proven adapter contract to copy<br>• The unified rubric to apply<br>• The dry-run view to reuse per portal |
| **S2 → S3** | • All 3 adapters<br>• Launcher runs sequential HAL → ISRO → GeM<br>• `hal/`, `isro/`, `gem/` `bids.db` populated with Pass 1 under the unified rubric<br>• `tool_db_path()` resolvable per portal | • 3 populated tool `bids.db` at known paths (merge sources)<br>• Each tool's schema to mirror into its parent table<br>• `pass1_*` columns present |
| **S3 → S4** | • `parent.db` with `{gem,hal,isro}_bids` (mirrored + overlay cols defaulted), `users`, `scrape_runs`<br>• Idempotent upsert callable in sequence | • Parent tables with `pass1_score` + `bid_status` to compute the tiered gate<br>• `scrape_runs` table to write run rows<br>• The merge step to invoke after each portal |
| **S4 → S5** | • Sequential orchestrator<br>• `scrape_runs` logging + `stage_timings_json`<br>• Gate output = score-5 set, score-4 set, CLOSED excluded<br>• systemd timer | • The score-5 queue (auto-run module) and score-4 set (regex preview)<br>• CLOSED-excluded lists<br>• `adapter.fetch_documents` (from S1/S2)<br>• Parent overlay columns to write<br>• `scrape_runs` counters (`summarized_count` / `local_extracted_count`) + stage timing to update |
| **S5 → S6** | • `bids/<source_pk>/` dirs with staged files (`.txt` + retained scans, with mtimes)<br>• Parent rows carrying `summary_json` (5) / `local_extract_json` (4)<br>• `docs_summarized` / `local_extracted` / `has_restrictive_eligibility` set | • `bids/` dirs with file mtimes to sweep (> 7 days)<br>• Parent rows to retain on CLOSED (keep `summary_json`/`local_extract_json`, remove files)<br>• `bid_status` / `closing_date` to drive the CLOSED sweep<br>• S4 stage timings to assert the overnight budget |
| **Cross-slice (non-adjacent): S1/S2 → S5** | • `adapter.fetch_documents` is produced at S1/S2 (per-portal acquisition contract) | • The S5 §8b module (and later web-app on-demand / "Fetch more" triggers) consume it<br>• A change to the fetch contract ripples forward to S5 though they aren't adjacent |

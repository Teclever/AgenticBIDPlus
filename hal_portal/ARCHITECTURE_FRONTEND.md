# Architecture — Front-End Integration

> **⚠️ SCOPE: FRONT-END INTEGRATION ONLY.**
> This document describes how the standalone **HAL Bid Automation** tool plugs
> into the new multi-portal **front-end web application**, and the target
> end-to-end workflow that application implements. It is **not** a description of
> the HAL tool's current standalone behaviour — for that, see `README.md` and
> `context/`. Where the target workflow differs from what the HAL tool does
> today, this document flags it explicitly under **"Delta vs. the standalone
> tool"**. Nothing here changes the HAL tool until those deltas are implemented.

---

## 1. Why this document exists

The HAL tool is one of several portal scrapers (GeM is another). The front-end
app is a single pane of glass over all of them. Each scraper stays
self-contained and portable; the front end owns everything cross-cutting:
consolidated storage, authentication, per-portal views, the vector database, the
summariser LLM, and retention/cleanup.

```
                         ┌────────────────────────────────────┐
                         │        FRONT-END WEB APP            │
                         │  (auth, per-portal views, API)      │
                         │                                     │
                         │  ┌───────────────┐  ┌────────────┐  │
   ┌──────────┐          │  │ Consolidated  │  │  Vector DB │  │
   │ HAL tool │──fetch──▶│  │   bids table  │  │ (per-bid   │  │
   │ (this    │  Pass 1  │  │ (tool + entry │  │  doc chunks)│  │
   │  repo)   │  docs    │  │  references)  │  └────────────┘  │
   └──────────┘          │  └───────────────┘  ┌────────────┐  │
   ┌──────────┐          │                     │ Summariser │  │
   │ GeM tool │──fetch──▶│        ...          │    LLM     │  │
   └──────────┘          │                     └────────────┘  │
                         └────────────────────────────────────┘
```

The HAL tool is the **scraper adapter**: it discovers bids, scores them (Pass 1),
and — when asked — fetches a bid's documents. It does **not** own the vector DB,
the summaries, or the UI.

---

## 2. Consolidated data model (front-end owned)

The front end maintains its **own** database, separate from each tool's local
SQLite. One consolidated `bids` row per (portal, source bid), with a hard link
back to the exact entry inside the originating tool so any bid can be traced to
"which tool, which row".

| Consolidated field | Source | Notes |
|--------------------|--------|-------|
| `id` | front end | Front-end surrogate key |
| `tool` | constant | `"hal"`, `"gem"`, … — identifies the scraper adapter |
| `source_pk` | tool | HAL: composite `(tender_number, line_number)` |
| `portal` | tool | Display/grouping key; HAL → `eproc.hal-india.co.in` |
| `title` / `description` | tool listing | `tender_description` for HAL |
| `buyer`, `region`, `closing_date`, `estimated_cost`, `emd` | tool listing | Listing fields |
| `pass1_score`, `pass1_rationale`, `pass1_domain`, `pass1_confidence` | tool Pass 1 | |
| `bid_status` | tool lifecycle | `NEW / ACTIVE / EXTENDED / CLOSED` |
| `docs_ingested` | front end | True once this bid's documents are in the vector DB |
| `summary` | front end | LLM summary text, generated on demand, then cached |
| `summary_generated_at` | front end | Timestamp of the cached summary |
| `user_state` | front end | e.g. `new / viewed / irrelevant / rejected` |

**Identity contract (HAL):** a bid is uniquely `(tender_number, line_number)`.
The front end must store both and treat them as the join key back into the HAL
tool. Tender numbers contain `/`; keep them raw in the DB and sanitise to `_`
only for any filesystem path.

**Portal isolation:** the UI never shows bids from multiple portals at once. The
user selects a portal first, then sees that portal's bids. The consolidated table
makes this a simple `WHERE tool = ?` / `WHERE portal = ?` filter.

---

## 3. Target end-to-end workflow

### 3.1 Ingest pipeline (scheduled, per portal)
For each scraper tool, on a schedule:

1. **Fetch** all new/active bids and upsert into the tool's local store, then
   sync listing fields up into the consolidated `bids` table (tagged with
   `tool` + `source_pk`).
2. **Pass 1 only.** Run the cheap capability score on every unscored bid. (Pass 2
   / Sonnet deep-scoring from the standalone tool is **not** part of this
   pipeline — see §5.)
3. **Conditional document download.** For every bid with `pass1_score >= 3`,
   download its required documents immediately (no human gate in between).
4. **Vectorise.** As soon as Pass 1 finishes and a qualifying bid's documents are
   downloaded, push the extracted/chunked document text into the **vector DB**,
   keyed by the bid's identity. Set `docs_ingested = true`.
5. **Delete the files.** Once vector-DB ingestion for a bid completes, **delete
   the downloaded files from disk**. No documents are stored permanently (§6).

### 3.2 Read path — login and browse
- User logs in and sees the newly-fetched bids **for one selected portal**.
- Each bid shows its listing fields + Pass 1 score/rationale.

### 3.3 "Fetch More Details" (on-demand summary)
When the user clicks **Fetch More Details** on a bid:

- **If the bid already has documents in the vector DB** (`docs_ingested = true`,
  i.e. it scored ≥ 3 and was ingested during §3.1):
  1. Retrieve the bid's chunks from the vector DB.
  2. Feed them to the summariser LLM.
  3. Show the summary to the user and **store it** in the consolidated DB
     (`summary`, `summary_generated_at`) so future opens are instant.
- **If the bid has no downloaded documents** (scored < 3, or not yet fetched):
  1. Trigger an **on-demand document fetch** for that single bid (the HAL tool's
     document-download path).
  2. Ingest the documents into the vector DB (set `docs_ingested = true`).
  3. Summarise via the LLM, show the user, store the summary.
  4. Delete the downloaded files from disk (§6).

The summary is generated once and cached; it is regenerated only if the bid's
documents change (e.g. an EXTENDED tender re-issues documents).

### 3.4 Retirement — closed / irrelevant / rejected
When a bid becomes `CLOSED`, or the user marks it **irrelevant** or **rejected**:

- **Purge all pertinent material from the system except the consolidated DB
  record.** Specifically: drop its chunks from the vector DB, delete any
  on-disk files, and (optionally) drop the cached `summary`.
- The **consolidated DB row is kept** as the durable record of what was seen and
  what the user decided. Nothing else about the bid survives.

---

## 4. What the HAL tool provides to the integration

These existing capabilities are the integration surface the front end drives.
(File references are in this repo.)

| Capability | Where | Output the front end consumes |
|-----------|-------|-------------------------------|
| Full scrape | `modules/fetcher.fetch_all_tenders` → `db.upsert_raw_tender` | Tenders in `data/bids.db`, keyed `(tender_number, line_number)`, with `bid_status` lifecycle |
| Pass 1 scoring | `modules/scorer_pass1.score_bids_pass1_bulk` | `pass1_score`, `pass1_confidence`, `pass1_domain`, `pass1_rationale`, `pass1_gaps` |
| Document download | `modules/fetcher.open_tender_documents` + `download_document` | Raw PDF **bytes** + filenames per tender (currently also written to `downloads/`) |
| PDF text extraction | `modules/scorer_pass2.extract_and_clean` | Cleaned, boilerplate-stripped text — ready to chunk for the vector DB |
| Lifecycle | `db.upsert_raw_tender`, `db.sweep_closed_tenders` | `NEW / ACTIVE / EXTENDED / CLOSED`, `extension_count`, `previous_closing_date` |
| CLI entry | `hal_tool.py` (`run`, `score-pending`, …) | Subprocess-invokable today |

**Identity & lifecycle are already correct for this design** — composite PK,
monotone flags, and the NEW→ACTIVE→EXTENDED→CLOSED transitions all hold.

---

## 5. Delta vs. the standalone tool

The current HAL tool implements a **different** Pass-2 stage than the target
workflow. These are the gaps a front-end integration must close. None are bugs in
the standalone tool; they are intentional differences in the new architecture.

| Concern | Standalone HAL tool today | Target front-end workflow |
|---------|---------------------------|---------------------------|
| Gate before documents | Human reviews `pass1_*.xlsx`, sets `Run Pass 2 = Y/N`, then `run-pass2` | **Automatic**: any `pass1_score >= 3` downloads documents immediately, no human gate |
| Document stage purpose | Pass 2 = **Sonnet deep-scoring** of cleaned text → `pass2_*` columns + recommendation | Documents → **vector DB**; deep analysis is replaced by **on-demand LLM summary** |
| Document persistence | Saved permanently under `downloads/{rec}/{date}/{tender}/` | **Deleted after vector-DB ingestion**; nothing kept on disk |
| Output surface | Daily Excel files (`pass1`, `pass2`, `bids`) | Consolidated DB + UI; Excel not required |
| Summaries | None | LLM summary generated on demand, cached in DB |
| Retention | DB + Excel + PDFs retained | DB record only after CLOSED/irrelevant/rejected; vector chunks + files purged |
| Vector DB | None | New component owned by the front end |

**Implication for the HAL tool.** To serve this workflow it needs (a) a
document-download entry point callable for a **single** bid without the Sonnet
scoring step (the building blocks — `open_tender_documents`, `download_document`,
`extract_and_clean` — already exist and just need a thin orchestration wrapper),
and (b) the auto-at-≥3 trigger moved out of the human-Excel gate. Pass 1
(`score_bids_pass1_bulk`) and the scrape are reusable as-is.

---

## 6. Retention & cleanup rules (hard requirements)

1. **No permanent file storage.** Downloaded documents are transient. The moment
   a bid's documents are ingested into the vector DB, the on-disk files are
   deleted. (In the standalone tool, `downloads/` is permanent — that behaviour
   must be turned off for the integrated pipeline.)
2. **Vector DB is the only document store**, and only for bids that are active and
   relevant.
3. **On CLOSED / irrelevant / rejected:** purge the bid's vector-DB chunks, any
   residual files, and optionally the cached summary. **Keep only the
   consolidated DB row.**
4. **Summaries are cached, not authoritative source** — they can be regenerated
   from the vector DB while the bid is still active, and are discarded on
   retirement.

---

## 7. Integration options (front end → HAL tool)

| Option | How | Trade-off |
|--------|-----|-----------|
| **Subprocess CLI** | Call `python hal_tool.py run` / `score-pending`; read `data/bids.db` | Lowest coupling; works today; coarse-grained (no single-bid doc fetch yet) |
| **Import as a library** | Import `modules.fetcher` / `modules.scorer_pass1` / `modules.scorer_pass2` directly | Fine-grained (single-bid document fetch, custom orchestration); requires the new wrapper from §5 |
| **Read shared SQLite** | Treat `data/bids.db` as the tool's output contract; sync into the consolidated DB | Good for the listing/Pass-1 sync; documents still need an explicit fetch call |

Recommended: **library import** for the ingest pipeline (gives the single-bid,
no-Sonnet document fetch the workflow needs) plus **shared-DB read** for syncing
listing + Pass 1 fields into the consolidated table.

When the multi-portal dashboard lands, this whole folder is intended to drop in
as `portals/hal/` with shared `core/` logic owned by the front-end project (see
`README.md`).

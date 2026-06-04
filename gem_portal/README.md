# GeM Portal — Starter Kit for the Vector-DB Pivot

This folder is a **self-contained snapshot** of the GeM portal logic, copied verbatim
from `../Implementation/` to seed a **new project** built around a vector database.

> The original `../Implementation/` tool is still in active use and was **not modified**.
> Everything here is a copy. Treat this folder as the starting point for the new build.

> **Note on the brief:** the request mentioned "the HAL portal" — this repo only contains
> the **GeM** (`bidplus.gem.gov.in`) fetch mechanism, so that is what is captured here.
> HAL/ISRO will be added later as separate portals following the same pattern.

---

## 1. The pivoted design (new workflow)

The old two-pass + Excel workflow is being replaced. The new daily flow:

1. **Daily morning fetch** — fetch all *new* bids not already in the DB; mark *closed*
   and *extended* bids. **This fetch logic does not change** (see §4).
2. **Snapshot the DB** — copy the database into this folder each run.
3. **Pass 1 scoring** — score new bids with the rubric (Haiku). For every bid scored
   **≥ 3**: fetch the **primary bid document**, parse it for **links to supporting
   documents**, fetch all relevant ones, and hold them in a **temporary location**.
4. **Ingest to vector DB** — all fetched documents are embedded into a **vector
   database**, keyed by **bid ID**. Then the pipeline stops. **No document is ever
   written to disk** — the vector DB is the only store of document content.

Then the system is idle until a user acts:

- The user opens the **web app** and sees the new bids.
- For a bid of interest, the user **requests further information**. Using a **separate
  rubric**, the system retrieves that bid's chunks from the vector DB, sends them to an
  **LLM to summarize**, shows the summary, and **saves the summary to the DB**.
  This happens **one bid at a time**.
- At that point the user **accepts or rejects** the bid.
- **Forced disposition:** every bid scored ≥ 3 has documents in the vector DB. A bid the
  user has **viewed** must be explicitly **accepted or rejected**. A bid the user
  **never views** is treated as **rejected**.
- **Vector-DB cleanup:** on rejection, that bid's documents are **removed** from the
  vector DB. Bids that become **CLOSED** in a future run are also **removed**.

### What is NET-NEW (to build in the new project — not present here)
- The **vector database** + embedding/ingest layer (keyed by bid ID).
- The **on-demand summary** step (second rubric → retrieve → LLM summarize → save).
- The **web application** (bid list, "request info", accept/reject, forced disposition).
- **Vector-DB lifecycle** hooks (remove on reject, remove on CLOSED).
- Replacing on-disk document saving with **temp-location → vector-DB** ingestion.

### What is REUSED from this folder
- Daily fetch + closed/extended marking (§4) — unchanged.
- Pass 1 scoring + rubric.
- The **document-fetch engine** (primary doc → link discovery → supporting docs).
- The SQLite bid lifecycle / schema.

---

## 2. File-by-file guide

### Orchestration & config
| File | Contents | Role in new workflow |
|------|----------|----------------------|
| `gem_tool.py` | The original CLI orchestrator. Wires the phases: ingest → **fetch** → CLOSED sweep → **Pass 1 score** → (Pass 2) → export. | **Reference for sequencing.** Reuse the fetch / sweep / Pass-1 phases. Drop the Pass-2-scoring and Excel-export phases; insert the doc-fetch → vector-DB-ingest step after Pass 1. |
| `config.py` | Paths (DB, state, exports, downloads, rubric), `PASS2_THRESHOLD=3`, loads `TARGET_ORGS` from `organizations.json`. | Keep. `PASS2_THRESHOLD=3` is your **"score ≥ 3"** cutoff for which bids get documents fetched. |
| `requirements.txt` | Python dependencies (`requests`, `anthropic`, `pdfplumber`, `openpyxl`, `pandas`). | Baseline deps. Add your vector-DB + embedding libs; `openpyxl`/`pandas` only needed if you keep Excel (you won't). |

### Fetch mechanism (GeM) — **the core deliverable**
| File | Contents | Role |
|------|----------|------|
| `modules/csrf_handler.py` | Establishes an authenticated `requests.Session` with GeM and extracts the CSRF token (`csrf_bd_gem_nk`). Detects CSRF-failure HTML pages. | **Required for every fetch.** GeM rejects requests without a valid session + token. See §4. |
| `modules/fetcher.py` | `search_bids()` (POST to `/search-bids`), `_parse_doc()` (maps raw Solr doc → bid dict), `fetch_all_bids_for_org()` (full pagination, no date filter, `numFound` coverage check). | **The fetch engine.** Unchanged in the new design. See §4. |
| `data/organizations.json` | `TARGET_ORGS` — the ministries/organizations to scan (Defence, MEITY, Space, Heavy Industries). | Drives which orgs are fetched. |
| `data/state.json` | Per-org `last_run` + crash-recovery checkpoints (`completed_orgs`). | Crash-recovery for long full-fetch runs. |

### Pass 1 scoring
| File | Contents | Role |
|------|----------|------|
| `modules/scorer_pass1.py` | Haiku batch scoring (batch size 25): builds a cached system prompt from the rubric + few-shots, runs an exclusion pre-filter, parses scores. | **Reuse as-is.** Produces the 0–5 score; **≥ 3 triggers document fetch**. |
| `data/capability_reference.md` | The scoring rubric / system prompt describing Teclever's capabilities. | The **Pass 1 rubric**. NOTE: the new **summary** step needs a **separate, second rubric** you will author. |
| `modules/feedback.py` | Seeds exclusion rules + few-shot examples; promotes feedback to rules. | Feeds the Pass 1 exclusion filter and few-shots. Keep. |

### Document-fetch engine (your step 3) — inside `scorer_pass2.py`
`modules/scorer_pass2.py` is a **mixed file**. Only the **document-retrieval half** is
relevant to the pivot; the LLM-scoring half is being retired.

| Function | Keep? | Why |
|----------|-------|-----|
| `download_pdf(internal_id)` | ✅ | Fetches the **primary bid PDF** (step 3a). |
| `extract_spec_links(pdf_bytes)` + `_rank_spec_url` / `_SKIP_URL_RE` / `_SPEC_URL_RANKS` | ✅ | Parses the primary PDF's hyperlink annotations to find **supporting/spec documents**, ranked & filtered (step 3b). |
| `_download_spec_pdf(url, session)` | ✅ | Downloads each supporting doc (auth vs public domains). |
| `extract_and_clean(pdf_bytes)` | ✅ (adapt) | Extracts + cleans PDF text (strips boilerplate, CID artifacts). Useful to produce **text for embedding**. |
| `_fetch_spec_texts()` | ✅ (adapt) | Orchestrates link → download → clean. **But it currently writes PDFs to disk (`_save_spec_pdf`) — remove that; route bytes/text to the vector DB instead.** |
| `_save_pdf` / `_save_spec_pdf` | ❌ | Disk saving — the new design stores **nothing on disk**. |
| `score_bid_pass2()` LLM call, `_handle_single_tender`, `extract_emd_amount` | ❌ (legacy) | Old Pass-2 scoring. Replaced by the on-demand vector-DB summary. EMD extraction can be salvaged later if needed. |

### Data layer
| File | Contents | Role |
|------|----------|------|
| `modules/db.py` | All SQLite ops: schema, `upsert_raw_bid` (NEW/ACTIVE/EXTENDED transitions + extension detection), `sweep_closed_bids`, `get_unscored_bids`, `query_pass2_candidates` (score ≥ threshold), human-override + run-flag preservation. | **Reuse the schema + bid lifecycle.** `query_pass2_candidates()` already selects the **≥ 3** set whose docs you must fetch. Add columns for the new flow: `summary_text`, vector-DB doc status, user disposition (accept/reject/viewed). |
| `data/bids.db` | **The live database snapshot** (~13 MB) — all bids with Pass 1/2 scores and lifecycle state. | Your **starting dataset**. Per workflow step 2, the daily run should also copy the DB into this folder. |

### Intentionally **excluded** (not copied)
- `excel_export.py`, `excel_ingest.py` — the Excel review workflow is replaced by the web
  app (human accept/reject + summaries live in the DB / UI, not spreadsheets).

---

## 3. Bid lifecycle (carried over unchanged)
`NEW → ACTIVE / EXTENDED → CLOSED`. Rules (enforced in `db.py`):
- `bid_number` is the primary key — always UPSERT.
- Extension detected when a re-fetched bid's `end_date` changes → `EXTENDED`, `extension_count++`.
- `sweep_closed_bids()` sets `CLOSED` where `end_date < today`. **CLOSED bids → remove from vector DB** (new).
- Human-owned fields are never overwritten by automated runs.

---

## 4. The GeM fetch mechanism (how it works)

**Daily fetch = full fetch, no date filtering.** Every run paginates *all* active bids per
org; "new vs updated vs extended" is decided at upsert time, not by a date window.

1. **Session + CSRF** (`csrf_handler.get_session()`): GET a GeM page to obtain cookies and
   scrape the `csrf_bd_gem_nk` token. All subsequent requests reuse this session + token.
   GeM returns a **200 HTML error page** on CSRF failure (not an HTTP error), so the code
   inspects the response and re-handshakes if needed.
2. **Search** (`fetcher.search_bids(ministry, org, page, session, token)`): POST to
   `/search-bids` with a JSON `payload` (search type = `ministry-search`, the ministry,
   the organization, and the page number) plus the CSRF token as form data. Returns Solr-style JSON.
3. **Parse** (`fetcher._parse_doc`): map each raw doc → bid dict:
   `bid_number`, `internal_id` (needed to download the PDF later), `ministry`,
   `organization`, `department`, `items`, `quantity`, `start_date`, `end_date`.
4. **Paginate** (`fetcher.fetch_all_bids_for_org`): loop pages until the portal returns
   `code 404` / `status 0` / empty `docs`. Page 1 captures `numFound`; if total fetched
   `< numFound`, emit a coverage warning (detects portal-side pagination caps). Polite
   `0.8s` delay between pages. An `on_page` callback upserts each page immediately.
5. **Upsert** (`db.upsert_raw_bid`): insert new bids as `NEW`; on re-fetch, detect
   `end_date` change → `EXTENDED`; otherwise `ACTIVE` (never reopen `CLOSED`).
6. **Closed sweep** (`db.sweep_closed_bids`): mark anything past its `end_date` as `CLOSED`.

> **TLS note (from the original project):** GeM switched to an eMudhra CA cert not in the
> default `certifi` bundle. If you hit `NO_CERTIFICATE_OR_CRL_FOUND`, append the GeM cert
> chain to certifi's bundle (do **not** use `REQUESTS_CA_BUNDLE`, it breaks the Anthropic SDK).

---

## 5. Suggested build order for the new project
1. Stand up fetch + DB lifecycle (copy §4 logic) → confirm daily fetch populates `new/closed/extended`.
2. Add Pass 1 scoring → produce ≥ 3 candidate set (`query_pass2_candidates`).
3. Adapt the doc-fetch engine to write to a **temp dir → vector DB** (drop disk saves).
4. Stand up the vector DB ingest keyed by bid ID.
5. Build the web app: bid list → request-info (2nd rubric → retrieve → summarize → save) → accept/reject + forced disposition.
6. Wire vector-DB cleanup on reject + on CLOSED.

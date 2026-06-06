# WEBAPP_HANDOFF.md — Teclever Bid Portal (front-end contract)

**As of:** 2026-06-04 · **Status:** the web app is a **later, separate round** (deferred per
`MASTER_ACTION_PLAN_V3.md` §9). This file is the running **contract the UI must honour** —
decisions accrue here as the backend firms up so the eventual front-end build inherits them
instead of re-deriving them. Authoritative rules live in [`AGENTS.md`](AGENTS.md); the data
model is in `MASTER_ACTION_PLAN_V3.md` §7.

---

## 1. Read model

The web app reads **only the master/parent DB** (`parent.db`, built at S3). The per-portal
`bids.db` files are **operational stores** (active bids, files, sync status) and are **not** a
front-end data source. The UI is **portal-segmented** (pick GeM / HAL / ISRO first).

## 2. Pass-1 score display (0–5) + provenance

Every bid carries `pass1_score` (0–5), `pass1_rationale`, and a **provenance** field
`pass1_method`:

| `pass1_method` | Meaning | Display |
|---|---|---|
| `model` | Scored by Haiku (Pass 1) | normal score chip + rationale |
| `keyword` | **Eliminated** by the pre-Pass-1 **two-pass** keyword gate (`neg_hit AND NOT pos_hit`); never sent to the model | score 0 + **"filtered" badge** (see §3) |

Eliminated bids also carry `auto_rejected=1`. The gate is **two-pass**: a bid that trips a
negative keyword but also matches the high-precision **positive in-scope list** is *rescued*
to the model (never filtered) — so a "filtered" bid is one that hit a negative **and** missed
every positive signal. Full spec: `_oldFiles/EliminatorDesignV2/ELIMINATOR_DESIGN.md`.

## 3. The soft-flag (load-bearing — do not implement as a hard filter)

The pre-Pass-1 eliminator removes obvious junk (office/catering/manpower/cleaning supplies)
**before** it costs a model call. The guarantee that makes this safe is **recoverability** —
so the UI contract is strict:

- **Eliminated bids are SHOWN, never hidden.** They appear in the list as **score 0 with a
  "filtered" badge**, visually distinct from a model-scored 0. Do **not** drop them from
  results, default-collapse them out of reach, or exclude them from counts.
- **Surface why.** On the bid, show `pass1_eliminated_by` — the matched keyword(s) — so a user
  can see *exactly* what triggered the filter (e.g. "filtered: `toner cartridges`").
- **Allow promote.** A user can **promote** a filtered bid **upward** (mark relevant, with a
  reason). This is a **confirmed false-elimination**, captured as `human_disposition='promoted'`
  + `human_reason` and fed to the ledger (see §5).
- **No information is destroyed.** Elimination only sets `pass1_score=0` +
  `pass1_method='keyword'` + `pass1_eliminated_by` + `auto_rejected=1`; the raw bid row is intact
  and re-scorable.
- **Surface shape.** The eliminated/scored bids render as a **sticky list, newest on top**
  (`ELIMINATOR_DESIGN.md` §6). First run shows the whole backlog (large); thereafter each day
  adds only the delta of newly fetched bids. Per bid the user can **promote** (with reason) or
  **accept**, plus a bulk **clear-table** (accept all un-promoted).

Rationale: protect-≥3 mining guarantees **zero** eliminations of any bid that scored ≥3
historically, and knowingly drops ~411 score-2 borderlines — a good trade **only while** the
soft-flag recoverability holds. Hard-hiding these bids breaks the safety model.

## 4. Score-gated actions ("Retrieve information")

Pass 2 = fetch document(s) → generate a **summary** for human decision. What the UI offers
depends on the score:

| Score | State when the user arrives | UI action |
|---|---|---|
| **5** | Summary already generated overnight | show summary immediately |
| **4** | Docs downloaded + text extracted overnight; **no summary yet** | **"Retrieve information"** → summary appears (no re-fetch — uses staged docs) |
| **≤3** | Nothing pre-done | **"Retrieve information"** → full fetch + extract + summary on demand (rare) |
| **CLOSED** | Terminal | data retained + viewable; **no AI action** (button disabled) |

All Pass-2 work goes through the single summarization module behind a global lock.

**Unreadable (legacy/binary) documents — surface, don't hide.** We deliberately do **not** run
LibreOffice, so legacy `.doc/.xls/.ppt` (and unknown binary) attachments can't be parsed and are
**not sent to the AI**. This is reported **inside the existing summary surface** — no new screen:
- Score-5 / on-demand summaries carry **`summary_json.unparsed_documents`** — a list of the
  filenames that could not be read. When non-empty, show a prominent **"⚠ Some documents could
  not be read"** notice with the filenames, alongside the (possibly partial) summary. The
  `render_markdown()` helper already emits this block at the top.
- Score-4 previews carry the same list at **`local_extract_json.unparsed_documents`**.
- If a bid had **only** unreadable docs, there is still a `summary_json` (a short "documents could
  not be read" record, `summary_model='local:unreadable-docs'`) — render it like any summary; the
  notice is the substance. These are the cases the operator tallies to decide whether legacy-format
  support is worth adding later.

## 5. Promote → ledger → governance feedback loop

The promote action in §3 is not just a UI re-rank — it drives the eliminator's self-correction
(full spec: `ELIMINATOR_DESIGN.md` §6–§9):

1. **Promote (with reason)** on a `pass1_method='keyword'` bid sets `human_disposition='promoted'`
   + `human_reason`, increments the matched term's `false_positives` in the
   `eliminator_keyword_stats` ledger, and **requeues the bid for Pass 1** (Haiku scores it for
   real).
2. **Accept / clear-table** on the remaining auto-rejected bids sets `human_disposition='accepted'`
   and increments each term's `confirmed_rejections` (confirmed-correct rejections). Pure code,
   no AI.
3. A **high-support** term (right on hundreds of junk bids, wrong on one exception) is **never
   auto-quarantined** — that re-admits all its junk. It's fixed by **strengthening the positive
   in-scope list**, not by weakening the negative list. Only low-support / low-precision terms
   quarantine.
4. Periodically (≈30–40 accumulated promotion-reasons, or weekly — whichever first) an **AI
   delta** proposes ADD/REMOVE/REFINE term changes → staged in `list_change_proposals` →
   exported to a **risk-colour-coded Excel** for **operator review on the deploy box** (NOT a
   web-app screen) → approved rows applied to `eliminator_terms` transactionally on the next
   run. Never silently trusted.

The web app owns surface **#1 only** (the bid list: promote / accept / clear-table). Surface
**#2** (term-list changes) is the **deploy-box Excel** under `$BIDPLUS_RUNTIME_DIR/list_review/`
— out of UI scope.

## 6. Rollout the UI should expect

The gate ships in **shadow mode** first (backend logs what it *would* eliminate but still
sends those bids to Haiku), so early on **no** bid will actually carry `pass1_method='keyword'`.
After the score-2 review and a clean shadow comparison, the gate flips hard and filtered bids
start appearing. Build the "filtered" badge + override path from day one regardless.

## 7. Other display rules (from `AGENTS.md`)

- **CLOSED** bids: retained with all data (`summary_json`/`local_extract_json` persist), shown as
  terminal, no new AI work — the nightly S7 sweep marks past-closing bids CLOSED and deletes their
  staged files (the DB row is the durable artifact).
- **7-day file window**: staged documents age out after 7 days (S7 retention sweep). The DB summary
  always remains; only re-fetch-needing actions are affected. A "Retrieve information" click on an
  **open** bid whose files have aged out triggers a re-fetch; on a **CLOSED** bid it does nothing.
- **EXTENDED** bids: `bid_status`/`extension_count`/`closing_date` update; the summary (if any)
  is unchanged — a bid is summarized at most once.
- **Sticky `system_alerts`**: a failed/partial nightly cycle raises a banner that persists
  until a human clears it in the app (never auto-cleared by a later success). The app renders
  the banner + a user-attributed "clear" action.
- **Restrictive eligibility**: `has_restrictive_eligibility` bids get a prominent go/no-go flag.
- **Unreadable documents**: when `summary_json.unparsed_documents` (or, for score-4,
  `local_extract_json.unparsed_documents`) is non-empty, show a "could not read N document(s)"
  notice with the filenames so the user knows the summary may be incomplete (see §4).

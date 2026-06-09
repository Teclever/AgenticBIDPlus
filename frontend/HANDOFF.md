# Teclever Bid Intelligence — Front-end handoff

**As of:** 2026-06-09  
**Location:** `frontend/` (this folder)  
**Authoritative UX/API spec:** [`../../webapp-design/WEBAPP_DESIGN.md`](../../webapp-design/WEBAPP_DESIGN.md) · [`../../webapp-design/API.md`](../../webapp-design/API.md)  
**Backend:** [`../../bidplus/web/`](../../bidplus/web/) (FastAPI, smoke-validated against `parent.db`)  
**Repo-wide status:** [`../../HANDOFF.md`](../../HANDOFF.md) §15

This document is the **current-state brief for the React front-end** — what was built in this
folder, what is validated vs pending, known footguns, and what the next agent should tackle.
It does not replace `WEBAPP_DESIGN.md` (behaviour/copy) or `API.md` (endpoint shapes).

---

## 1. What this folder is

The **production web UI** lives here — not a fork. FastAPI serves the built output from exactly:

```
frontend/dist/
```

See `bidplus/web/app.py` (`_DIST` path). Do **not** move or copy this project elsewhere.

| Asset | Role |
|-------|------|
| `src/` | React app (Vite + React Router + Tailwind 4 + shadcn/Radix) |
| `dist/` | Production build — served by FastAPI on port 8000 |
| `src/mocks/` | MSW handlers + copied fixtures (offline dev; currently **off**) |
| `../../webapp-design/` | Design spec, API contract, screenshots, HTML mockups |

The Figma-derived prototype in this tree was the **visual foundation**; behaviour and copy follow
`WEBAPP_DESIGN.md` where they differ.

---

## 2. Stack and key files

**Stack:** Vite 6 · React 18 · React Router 7 · Tailwind 4 · TypeScript · MSW (optional) · react-markdown

| Path | Purpose |
|------|---------|
| `src/app/lib/api.ts` | Central `apiFetch` — `credentials: "include"`, 401 → `/login` |
| `src/app/lib/types.ts` | API response TypeScript types |
| `src/app/lib/format.ts` | Dates, filter labels, bid detail path helper |
| `src/app/context/AuthContext.tsx` | Session state via `GET /api/auth/me` |
| `src/app/components/AuthGuard.tsx` | Redirect unauthenticated users to `/login` |
| `src/app/components/Layout.tsx` | Header, nav, bell, logout |
| `src/app/components/NotificationPanel.tsx` | Auto-filtered review overlay |
| `src/app/components/Pagination.tsx` | Bid list prev/next |
| `src/app/pages/*.tsx` | One file per screen (see §4) |
| `src/mocks/handlers.ts` | MSW — maps `API.md` §8 fixtures |

**Env files:**

| File | `VITE_API_BASE` | `VITE_ENABLE_MSW` |
|------|-----------------|-------------------|
| `.env.development` | *(empty = same-origin)* | `false` |
| `.env.production` | *(empty)* | `false` |

Empty `VITE_API_BASE` means relative `/api/...` URLs (correct for port 8000 and for Vite proxy).

---

## 3. How to run

### Recommended — single origin (production-like)

From repo root:

```bash
bash bidplus/scripts/run_web.sh
```

- Builds `dist/` if missing or stale  
- Starts FastAPI on **http://localhost:8000** (API + UI same origin; cookies work)  
- Requires `BIDPLUS_RUNTIME_DIR` (default `~/bidplus-runtime`) and venv from `setup_runtime.sh`

**Login user** (create if needed):

```bash
export BIDPLUS_RUNTIME_DIR=~/bidplus-runtime
~/bidplus-runtime/venv/bin/python -m bidplus.users list
~/bidplus-runtime/venv/bin/python -m bidplus.users add you@teclever.com yourpassword
```

### Optional — Vite dev server (hot reload)

Requires **both** processes:

```bash
# Terminal 1
bash bidplus/scripts/run_web.sh

# Terminal 2
cd "frontend"
npm run dev
```

Open the URL Vite prints (often **5173**; may shift to **5174** if 5173 is taken).  
`vite.config.ts` proxies `/api` → `localhost:8000`. CORS on FastAPI allows 5173/5174.

**Do not** set `VITE_API_BASE=http://localhost:8000` in dev — that breaks cookie auth cross-origin.

### Rebuild after front-end changes

```bash
cd "frontend"
npm run build
# restart run_web.sh (or hard-refresh if it auto-serves new dist)
```

### Mock API (offline UI work)

Set `.env.development` → `VITE_ENABLE_MSW=true`, restart `npm run dev`. Fixtures in
`src/mocks/fixtures/` (copied from `webapp-design/fixtures/`). Flip back to `false` before
testing against the real API.

---

## 4. Screens — build status

| Screen | Route | Status | Notes |
|--------|-------|--------|-------|
| **Login** | `/login` | **Working** | Teclever email label, disabled Sign In until fields filled, error dialog. Enter key submits; double-submit guarded. |
| **Dashboard** | `/` | **Working (updated 2026-06-09)** | Three portal cards. Opportunity Distribution chips show **new / accepted** separately per score band (rejected excluded). Top stat tiles = New / Accepted. Single Tender amber chip (when > 0). Closing Soon note corrected. |
| **Bid list** | `/portal/:portalId` | **Working** | Sorted newest-first. Inline Accept/Reject buttons on each row. Single Tender badge (green ★ for Teclever, amber for others). Filter `singletender` added. `rfilter/rpage/ridx` passed to detail links for next-bid navigation. |
| **Bid detail** | `/portal/:portalId/bid/:bidKey` | **Working (updated 2026-06-09)** | Accept/Reject navigates to next bid in filtered list; generation-counter prevents stale state. Back arrow returns to filtered list (or browser history if no return context). Documents section with on-demand download. Single Tender banner (green/amber + org name). |
| **Activity log** | `/activity` | **Built, needs validation** | Paginated `GET /api/activity`. |
| **Notifications** | Bell overlay | **Working** | Save-all now also bulk-rejects auto_rejected bids. Dispute modal, per-user red dot. |
| **System Alerts** | Shield icon overlay | **Working (2026-06-09)** | Nightly run history at top (per-portal auto-scored / AI-scored / summarised). Active/cleared alerts below. |

---

## 5. Global behaviour (implemented)

- **Auth:** httpOnly cookie `bidplus_session`; every API call uses `credentials: "include"`.
- **401 / unauthenticated:** redirect to `/login`.
- **Filtered bids:** always shown (rating 0 + badge + `eliminatedBy`); never hidden.
- **Notification Save all:** `POST /api/notifications/auto-filtered/save-all` — clears governance queue AND bulk-sets `user_state='rejected'` on all `auto_rejected=1 AND user_state='new'` bids.
- **Generate Summary:** spinner + disabled button; handles 200 / 409 `summarization_busy` / error. Error persists across navigation via `generationState.ts` `errors` Map; shown in spinner slot.
- **Cross-user generation banner:** `Layout.tsx` polls `GET /api/generating` every 5 s. Banner is a clickable `<Link>` to the bid detail page.
- **Accept/Reject:** only when `userState === "new"` AND `method === "model"`. After disposition, fetches same filtered page and navigates to first bid that isn't the disposed one (handles filters that don't exclude rejected bids). Generation counter: stale callbacks after navigation are silently discarded.
- **Back navigation:** `BidDetail` back arrow navigates to `/portal/${id}?filter=${rFilter}` when return context params (`rfilter`, `rpage`, `ridx`) are present; falls back to `navigate(-1)` otherwise.
- **Document download:** `fetch()` with `credentials: include` hits `GET /bids/{key}/documents/download`. Backend auto-fetches from portal if staging dir is empty; single file → direct; multiple → ZIP. Download continues after user navigates away; error only shown if user is still on same bid (generation counter in `downloadGenRef`).
- **Single Tender badge / banner:** `SingleTenderBadge` in `PortalBids.tsx` (green ★ for Teclever org, amber for others). Coloured banner in `BidDetail.tsx`.

---

## 6. Known issues and footguns (read before debugging)

### 6.1 Auth / cookies / empty dashboard

The most common failure mode: **login succeeds but dashboard shows no cards** (or previously all
zeros). Root cause is usually the **session cookie not reaching** `/api/portals/*/stats`:

- Use **http://localhost:8000** via `run_web.sh` (simplest).
- Do not point `VITE_API_BASE` at `http://localhost:8000` while browsing on 5173/5174.
- After front-end changes: `npm run build` + restart `run_web.sh` + hard refresh (Cmd+Shift+R).
- `uvicorn` is **not** on global PATH — use `run_web.sh` or `~/bidplus-runtime/venv/bin/uvicorn`.

Historical fixes already in tree:

- `api.ts`: empty `VITE_API_BASE` → relative URLs (not fallback to `:8000`).
- Login verifies session via `refresh()` after `POST /login`.
- Dashboard keys stats by request portal id; shows Retry on failure instead of silent empty grid.
- GET requests no longer send `Content-Type: application/json`.
- FastAPI CORS for localhost:5173/5174; Vite proxy with `cookieDomainRewrite`.

### 6.2 Data correctness — needs operator review

The operator has flagged that **displayed numbers sometimes do not look right**. Treat as
**open investigation** — verify API vs UI separately:

**Stats API field names (updated 2026-06-09):**

| `counts` field | Definition | Filter key |
|----------------|------------|------------|
| `new` | `user_state='new'` | `new` |
| `accepted` | `user_state='accepted'` | — |
| `scoreBelow4New` | score 1–3, user_state='new' | `score1to3` |
| `scoreBelow4Accepted` | score 1–3, user_state='accepted' | `score1to3` |
| `scoreExact4New` | score 4, user_state='new' | `score4` |
| `scoreExact4Accepted` | score 4, user_state='accepted' | `score4` |
| `scoreExact5New` | score 5, user_state='new' | `score5` |
| `scoreExact5Accepted` | score 5, user_state='accepted' | `score5` |
| `singleTender` | `is_single_tender=1` | `singletender` |
| `highPriority` | `user_state='accepted'`, closing ≤10 days | `highpriority` |
| `closingSoon` | score 3–5, not rejected, closing ≤10 days | `closingsoon` |
| `closingSoonActionable` | accepted, closing ≤10 days | `closingactionable` |

Window is **10 days** (changed from 7). `closingSoonActionable` replaces the old `bidsClosingBy` field and is the headline clickable number on each dashboard card.

| Area | What to check |
|------|----------------|
| **Dashboard buckets** | Verify field names above against `GET /api/portals/{portal}/stats` response; `new` = all rows with `user_state='new'` (may equal `total` if nothing dispositioned yet). |
| **Bid list `total`** | Paginated `total` from API vs rows on screen (50 per page). Header count is **full filtered total**, not page length. |
| **Ratings / Filtered** | `pass1_score` + `pass1_method='keyword'` → rating 0 + Filtered badge; distinct from model-scored 0. |
| **Summaries** | Score-5 overnight vs score-4 local extract vs on-demand Sonnet — `summary.available` / `summary.markdown`. |
| **HAL composite keys** | `bidKey` = `tender_number\|line_number`; must be URL-encoded in paths. |

**Sanity check command** (authenticated stats, no browser):

```bash
export BIDPLUS_RUNTIME_DIR=~/bidplus-runtime
~/bidplus-runtime/venv/bin/python -c "
from fastapi.testclient import TestClient
from bidplus.web.app import app
from bidplus import merge
from bidplus.web.auth import create_session
c = TestClient(app)
p = merge.connect_parent()
tok, _ = create_session(p, 1, False)
for portal in ('gem','hal','isro'):
    r = c.get(f'/api/portals/{portal}/stats', cookies={'bidplus_session': tok})
    print(portal, r.status_code, r.json().get('counts') if r.status_code==200 else r.text)
p.close()
"
```

Compare output to what the UI shows. If API is correct but UI is wrong → front-end bug. If API
looks wrong → `bidplus/web/app.py` / `parent.db` / merge state.

### 6.3 Not yet exercised end-to-end in browser

- **Generate Summary** — partially exercised (2026-06-08): live test on HAL bid (`TENDER NOTICE/NCP/21/26-27`). First attempt got a 500 (transient HAL Playwright first-boot issue — browser profile now exists; subsequent calls succeed). Error display fix verified. **Score-4 "Retrieve information" flow** (local-only, no Sonnet) and **409 lock-busy path** still not exercised in browser.
- **Notifications** Save all / dispute against live `auto_rejected` queue.
- **Disposition** Accept/Reject → activity log row.
- **System alert** sticky banner (API exists: `GET /api/system-alert`; UI component not built — lowest priority).
- **Mobile** layouts at all breakpoints.
- **ISRO** bid list and detail with live data (HAL partially tested; most dev testing used GEM).

### 6.4 Generate Summary — error propagation fix (2026-06-08)

**Root cause (now fixed):** React component state is destroyed on unmount. When the user
navigated away while a summary was generating (or after it errored), the error message was lost.

**Fix — two files:**

- **`src/app/lib/generationState.ts`** — extended with a module-level `errors: Map<string, string>`.
  New exports: `setGenerationError(key, msg)`, `clearGenerationError(key)`, `getGenerationError(key)`.
  `startGenerating()` now clears the prior error for the key.

- **`src/app/pages/BidDetail.tsx`** — load `useEffect` hydrates `generateError` from
  `getGenerationError(_genKey)` on mount. `handleGenerateSummary` calls `clearGenerationError` on
  success and `setGenerationError` on failure. The error banner was also **moved** from below the
  Generate button into the spinner ternary slot (same visual position as the spinner), so it is
  never off-screen or hidden by scroll.

**Error display order in the summary section (no summary yet):**

```
generating             → spinner banner (blue)
generateError          → error banner (red)
otherBidGenerating     → "another bid generating" banner (blue)
(none)                 → "No summary yet" text
```

**Committed:** `455358f` · **Deployed to box:** rsync of `dist/` (dist is gitignored; rsync is the
deploy path — `git pull` on the box only needed for source, not for the running app).

---

### 6.5 Cross-user generation banner (2026-06-08)

**What it does:** the blue "Generating AI summary for …" banner in `Layout.tsx` is now visible
across all logged-in browsers/users, not just the one that triggered the summary.

**How it works — three layers:**

1. **Backend** (`bidplus/web/app.py`) — module-level `_active_job: dict | None` set when the
   lock is acquired in `generate_summary`, cleared in `finally`. TTL 300 s guards against the
   browser-closed-mid-generation edge case. `GET /api/generating` → `{"active": {...} | null}`.

2. **State module** (`src/app/lib/generationState.ts`) — added `serverGenerating: ServerState | null`
   and `setServerGenerating()`. `getAnyGenerating()` returns local optimistic state first (instant
   for the triggering tab), then falls back to `serverGenerating` (cross-user). `getOtherGenerating()`
   similarly checks both.

3. **API** (`src/app/lib/api/system.ts`) — `generatingApi.get()` wraps `GET /api/generating`;
   silently returns `{active: null}` on error so a stale banner is never shown as a broken UI.

4. **Layout** (`src/app/components/Layout.tsx`) — `pollServerGenerating` called once on mount,
   then every 5 s via `genInterval`. Subscribes to `generationState` changes so the banner updates
   immediately on local state changes. Banner is a `<Link>` to the bid detail page.

**MSW stub:** `handlers.ts` mocks `GET /api/generating` → `{active: null}` (always idle in dev
fixtures mode).

---

### 6.6 Legacy prototype artefacts

- `src/app/lib/mockData.ts` — original Figma mock data; **not used** by wired screens.
- `src/app/components/ui/Button` imports in old paths — canonical file is `button.tsx`.

---

## 7. Recommended next steps (priority order)

> **Deploy box is live at `http://192.168.2.193:8000`** (served by `bidplus-web.service`).
> First nightly run fires at **01:00 IST tonight (2026-06-09)** — that is the S6/S7 DONE-WHEN gate.

1. **Verify dashboard on the deploy box** — log in at `http://192.168.2.193:8000`; confirm three
   portal cards show non-zero totals. Use the Python sanity-check in §6.2 if cards look wrong.
2. **Data audit** — for each portal, spot-check dashboard buckets vs manual SQL on the box's
   `parent.db` (`gem_bids`, `hal_bids`, `isro_bids`); discrepancies point to API or merge logic.
3. **Bid list** — confirm pagination (`page`/`pageSize=50`), filters (`score1to3`, `score4`, `score5`,
   `closingsoon`, `closingactionable`, `highpriority`), and Filtered badge rows visible.
4. **Bid detail: score-4 "Retrieve information"** — pick a score-4 bid; click Generate Summary; confirm
   it runs `local_extract_bid` (no Sonnet, fast), returns `summary.available=true` immediately.
5. **Bid detail: Generate Summary 409 path** — start a summary, immediately open a second bid in
   another tab, confirm the "another bid generating" banner appears.
6. **Disposition** — Accept/Reject a bid on a score-5 or score-4 bid; confirm activity log row.
7. **Notifications** — bell queue, Save all, dispute one filtered bid; confirm `disputed` activity row.
8. **System alert banner** — lowest priority (API: `GET /api/system-alert`; UI panel not yet built).
9. **Post nightly run (2026-06-09 ~01:00 IST)** — verify score-5 summaries appeared, Pass 2 ran,
   lifecycle sweep closed expired bids, budget report is within 9am.

---

## 8. Build order reference (for new agents)

Per `webapp-design/BUILD.md`:

1. Work **in this folder** (never fork).
2. Mock first (`VITE_ENABLE_MSW=true`) when building UI without backend.
3. Build screens against `webapp-design/screenshots/target-*`.
4. Wire to real API (`VITE_ENABLE_MSW=false`, `run_web.sh`).
5. `npm run build` → FastAPI serves `dist/`.

**Load-bearing rules:** Filtered bids never hidden · Save all clears notification queue · HAL
composite `bidKey` · Generate Summary 409 handling · closing window = `stats.windowDate` from API.

---

## 9. Related docs (do not duplicate)

| Document | Use for |
|----------|---------|
| [`webapp-design/WEBAPP_DESIGN.md`](../../webapp-design/WEBAPP_DESIGN.md) | UX, screenshots, behaviour |
| [`webapp-design/API.md`](../../webapp-design/API.md) | Endpoint request/response shapes |
| [`webapp-design/BUILD.md`](../../webapp-design/BUILD.md) | Zero-context build guide |
| [`WEBAPP_HANDOFF.md`](../../WEBAPP_HANDOFF.md) | Read model, soft-flag, score-gated actions |
| [`HANDOFF.md`](../../HANDOFF.md) §15 | Backend web layer status |
| [`DEPLOY_WORKFLOW.md`](../../DEPLOY_WORKFLOW.md) | Deploy-box provisioning |

---

## 10. Document history

| Date | Change |
|------|--------|
| 2026-06-06 | Initial front-end handoff — implementation in `UIReference/…`, login working, dashboard/stats auth issues debugged, pagination + API wiring landed, data accuracy flagged for review |
| 2026-06-08 | Folder renamed `frontend/` (was `UIReference/Teclever Bid intelligence/`). Deploy box provisioned and running at `192.168.2.193:8000`. Timer fixed to 01:00 IST (`b04f044`). Generate Summary error propagation bug fixed (`455358f`): errors persist across navigation via `generationState.ts` errors Map; error shown in spinner slot. Live test on HAL bid confirmed fix. |
| 2026-06-08 | **Stats API field rename + Dashboard UI overhaul.** Backend renamed all stats `counts` fields (old `score3plus/score4plus/bidsClosingBy` → new `scoreBelow4/scoreExact4/scoreExact5/closingSoonActionable`; window 7→10 days). Three closing categories: `closingSoon` (score 3–5, not rejected), `closingSoonActionable` (score 5 or accepted), `highPriority` (accepted — now date-based). Frontend: `types.ts`, `BidFilter` type, `FILTER_LABELS`, `VALID_FILTERS` updated; Dashboard bar chart replaced with clickable chip grid; actionable count links to `?filter=closingactionable`. |
| 2026-06-08 | **Score 0 filter added.** Backend: `filtered` key → `pass1_score = 0` (all score-0 bids — both keyword-eliminated and model-scored 0). Frontend: `BidFilter`, `FILTER_LABELS` ("Score 0 bids"), `VALID_FILTERS`, quick-filter chip list, MSW handler. The "Filtered" badge on each card still distinguishes sub-types visually. |
| 2026-06-08 | **Cross-user generation banner + Login Enter key fix.** `generationState.ts` extended with cross-user logic. `api/system.ts` adds `generatingApi.get()`. `Layout.tsx` polls every 5 s; banner is a clickable `<Link>`. Login Enter-key submit. |
| 2026-06-09 | **Nightly run history in System Alerts panel.** `RunCard` component shows per-portal rows with auto-scored / AI-scored / summarised breakdown. `scrape_runs` gained `keyword_scored_count` + `model_scored_count` (additive migration); backfilled via SSH for the 2026-06-09 nightly run. |
| 2026-06-09 | **Dashboard Opportunity Distribution redesign.** Score chips show `new` + `accepted` separately (rejected excluded). Top stat tiles changed from Total/New → New/Accepted (green accent). Single Tender amber chip (when > 0). `PortalStats.counts` extended with 6 new fields + `singleTender`. |
| 2026-06-09 | **Filter persistence + next-bid navigation.** Back button uses explicit return URL (`/portal/${id}?filter=${rFilter}`) when return context is set. `PortalBids` encodes `rfilter/rpage/ridx` into every bid-detail link. After Accept/Reject, `navigateToNext` fetches the same filtered page and skips the just-disposed bid key (handles filters like `score1to3` that keep rejected bids in the list). Generation counter (`downloadGenRef`) prevents stale state updates after navigation. |
| 2026-06-09 | **Document download.** `GET /api/portals/{portal}/bids/{key}/documents/download` auto-fetches from portal if staging dir is empty; single file → direct, multiple → ZIP. Frontend uses `fetch()` with generation counter: download completes even after navigation, errors only shown if user still on same bid. |
| 2026-06-09 | **Single Tender detection.** New DB columns `is_single_tender` + `single_tender_org` (all portal tables). Detection in `summarize.py` via liberal regex; Teclever → score 5 + Sonnet; masked → score 5 + Sonnet; other → auto-rejected. `launcher singletender-backfill` scans existing `.txt` files. Frontend: `singletender` filter, `SingleTenderBadge` (green ★ Teclever / amber generic) in list rows and mobile cards, coloured banner in BidDetail. Dashboard: amber Single Tender chip. |

*Update this file when validation state changes or new screens ship.*

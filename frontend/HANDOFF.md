# Teclever Bid Intelligence — Front-end handoff

**As of:** 2026-06-06  
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
| **Login** | `/login` | **Working** | Teclever email label, disabled Sign In until fields filled, error dialog, no footer/forgot-password. Post-login calls `refresh()` (`/api/auth/me`) before navigate. |
| **Dashboard** | `/` | **Partial** | Three portal cards wired to `GET /api/portals/{id}/stats`. Login works; stats have been flaky (empty cards, zeros) when session cookie not sent — see §6. **Data accuracy needs review** (bucket definitions vs operator expectation). |
| **Bid list** | `/portal/:portalId` | **Built, needs validation** | API pagination (`page`/`pageSize=50`), filter banner, Filtered badge, mobile cards. Header shows `total` from API. |
| **Bid detail** | `/portal/:portalId/bid/:bidKey` | **Built, needs validation** | Single column, Generate Summary, Accept/Reject, markdown summary. HAL `bidKey` URL-encoded (`tender\|line`). |
| **Activity log** | `/activity` | **Built, needs validation** | Paginated `GET /api/activity`. |
| **Notifications** | Bell overlay | **Built, needs validation** | Save all, dispute modal, per-user red dot. |
| **System alert banner** | — | **Not built** | API exists (`GET /api/system-alert`); lowest priority per `API.md` §7. |

---

## 5. Global behaviour (implemented)

- **Auth:** httpOnly cookie `bidplus_session`; every API call uses `credentials: "include"`.
- **401 / unauthenticated:** redirect to `/login` (central `apiFetch` + Dashboard `navigate` fallback).
- **Filtered bids:** always shown (rating 0 + badge + `eliminatedBy`); never hidden from lists.
- **Notification Save all:** `POST /api/notifications/auto-filtered/save-all` — primary queue clear.
- **Generate Summary:** spinner + disabled button; handles 200 / 409 `summarization_busy` / generic error.
- **Accept/Reject:** only when `userState === "new"` AND `method === "model"`.

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

| Area | What to check |
|------|----------------|
| **Dashboard buckets** | `GET /api/portals/{portal}/stats` — definitions in `WEBAPP_DESIGN.md` §16.9 / `API.md` §2. `closingSoon` / `bidsClosingBy` use `lifecycle.parse_closing` over per-portal date columns; `new` = all rows with `user_state='new'` (may equal `total` if nothing dispositioned yet). |
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

- **Generate Summary** with real Sonnet (cost + network; lock / 409 path wired).
- **Notifications** Save all / dispute against live `auto_rejected` queue.
- **Disposition** Accept/Reject → activity log row.
- **System alert** sticky banner.
- **Mobile** layouts at all breakpoints.
- **HAL / ISRO** bid list and detail with live data (most dev testing used GEM).

### 6.4 Legacy prototype artefacts

- `src/app/lib/mockData.ts` — original Figma mock data; **not used** by wired screens.
- `src/app/components/ui/Button` imports in old paths — canonical file is `button.tsx`.

---

## 7. Recommended next steps (priority order)

1. **Stabilise dashboard on port 8000** — log in, confirm three cards show non-zero totals
   matching the Python sanity check above.
2. **Data audit** — for each portal, spot-check dashboard buckets vs manual SQL on `parent.db`
   (`gem_bids`, `hal_bids`, `isro_bids`); file discrepancies against API or merge logic.
3. **Bid list** — confirm pagination, filters (`closingsoon`, `highpriority`), Filtered rows visible.
4. **Bid detail** — open a score-5 bid with summary, a score-4 bid (Generate Summary), a filtered bid.
5. **Notifications** — bell queue, Save all, dispute one bid; confirm activity log `disputed` row.
6. **Generate Summary** — test `GEM/2026/B/7605377` or `GEM/2026/B/7489616` (staged docs on disk).
7. **System alert banner** — last, per spec.
8. **Commit** front-end + `run_web.sh` + CORS changes when operator is satisfied.

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

*Update this file when validation state changes or new screens ship.*

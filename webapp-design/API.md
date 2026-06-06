# API.md — Frontend API contract (Teclever Bid Intelligence)

**Audience:** the front-end agent building the React app. **You do not build the backend** —
it is implemented in this repo (Python + FastAPI, `bidplus/web/`). This file is the **contract
you code against**, and the [`fixtures/`](fixtures/) folder holds **mockable sample responses** so
you can build the whole UI before the real server exists.

> Behaviour/copy precedence: [`WEBAPP_DESIGN.md`](WEBAPP_DESIGN.md) → this file → the prototype.
> The endpoint **shapes** here are authoritative; the design doc's per-section "Backend contract"
> tables are summaries. The design doc's **§16** is the *backend* implementation spec (in-repo) —
> you don't need it, but the field names below are derived from it.

---

## 0. Conventions

- **Base URL:** same origin. Dev: set `VITE_API_BASE` (default `http://localhost:8000`). In prod
  the FastAPI app serves your built `dist/` at the same origin, so calls are relative (`/api/...`).
- **Auth:** cookie session. `POST /api/auth/login` sets an **httpOnly** cookie
  `bidplus_session`; send `credentials: "include"` on every request. A `401` means
  not-authenticated → redirect to `/login`.
- **Content type:** `application/json` for request + response bodies.
- **Portal id:** `gem | hal | isro` (lowercase) everywhere.
- **`bidKey`:** the bid's primary key. In **JSON bodies** it appears **decoded**; in **URL paths**
  it must be **URL-encoded**. HAL is composite — `tender_number|line_number` joined with a literal
  `|` (e.g. `HAL/KPT/ED/E-PROC/WC-1245/1|WC-1245`). GeM/ISRO are single-segment.
- **Pagination:** list endpoints take `?page=1&pageSize=50` and return
  `{ items: [...], page, pageSize, total }`.
- **Timestamps:** ISO-8601 UTC (`2026-06-06T04:12:00Z`) where the backend could parse them; an
  unparseable portal date is returned as the **raw string** in `*Raw` fields (render verbatim).
- **Errors:** non-2xx return `{ "error": { "code": "<slug>", "message": "<human text>" } }`.
  Codes you must handle: `invalid_credentials` (401), `unauthenticated` (401),
  `not_found` (404), `summarization_busy` (409), `bid_closed` (422), `non_teclever_email` (422).

---

## 1. Auth

### `POST /api/auth/login`
Request: `{ "email": "user@teclever.com", "password": "…", "rememberMe": true }`
- `200` → `{ "user": { "id": 1, "email": "user@teclever.com" } }` + sets cookie.
  `rememberMe:true` → 30-day cookie; else 12-hour.
- `401 invalid_credentials` → show the error dialog (WEBAPP_DESIGN §4.3).
- `422 non_teclever_email` → email isn't on the `teclever` domain.

### `POST /api/auth/logout`
`204`, clears the cookie. Redirect to `/login`.

### `GET /api/auth/me`
- `200` → `{ "id": 1, "email": "user@teclever.com" }` — see [`fixtures/auth-me.json`](fixtures/auth-me.json).
- `401 unauthenticated`.

---

## 2. Dashboard stats

### `GET /api/portals/{portal}/stats`
Per-portal aggregates for the dashboard card (WEBAPP_DESIGN §5 / §16.9). Example:
[`fixtures/portal-gem-stats.json`](fixtures/portal-gem-stats.json).

```json
{
  "portal": "gem",
  "windowDate": "2026-06-13",
  "counts": {
    "total": 11333, "new": 420,
    "score3plus": 210, "score4plus": 62, "score5": 23,
    "highPriority": 40, "closingSoon": 18, "bidsClosingBy": 12
  }
}
```
- `windowDate` = today + **7 calendar days** (hardcoded). **Display it on the card** verbatim
  ("Bids Closing By 13 Jun 2026").
- Bucket meanings: `highPriority` = rating ≥4 & New; `closingSoon` = New & closing ≤ windowDate;
  `bidsClosingBy` = rating 4–5 & New & closing ≤ windowDate. The distribution bar uses
  `score3plus / score4plus / score5 / highPriority / closingSoon` (labelled 3+ / 4+ / 5 / HP / CS).

The dashboard can call all three portals (`gem`, `hal`, `isro`) and render three cards.

---

## 3. Bid listing

### `GET /api/portals/{portal}/bids`
Query params (all optional): `page`, `pageSize`, `search` (free text over id/title/buyer),
`filter` (one of `all | new | score3plus | score4plus | score5 | highpriority | closingsoon`),
`status` (`new | accepted | rejected`). Default sort: **rating desc**.
Example page: [`fixtures/portal-gem-bids.json`](fixtures/portal-gem-bids.json).

Each `items[]` is a **bid list item** (lighter than the detail object — no summary markdown):

```json
{
  "portal": "gem",
  "bidKey": "GEM/2026/B/7605377",
  "bidId": "GEM/2026/B/7605377",
  "title": "Supply & Installation of Environmental Test Chamber",
  "buyer": "ISRO Propulsion Complex",
  "rating": 5,
  "method": "model",
  "eliminatedBy": null,
  "autoRejected": false,
  "userState": "new",
  "bidStatus": "OPEN",
  "hasRestrictiveEligibility": true,
  "summaryAvailable": true,
  "closingDate": "2026-06-13T17:00:00Z",
  "closingDateRaw": "2026-06-13T17:00:00Z"
}
```

- `rating` is `0–5` or `null` (unscored). **Filtered** bids (`method:"keyword"`) render as rating
  **0 + "Filtered" badge + `eliminatedBy` sub-line** (WEBAPP_DESIGN §6.5); never hide them.
- `summaryAvailable` tells the list whether the detail will show a stored summary (score-5) or the
  "Generate Summary" button.

---

## 4. Bid detail

### `GET /api/portals/{portal}/bids/{bidKey}`
`bidKey` URL-encoded in the path. Returns the **full bid detail object**. Examples:
[`fixtures/bid-detail-score5.json`](fixtures/bid-detail-score5.json) (stored summary),
[`fixtures/bid-detail-filtered.json`](fixtures/bid-detail-filtered.json) (eliminated bid).

```json
{
  "portal": "gem",
  "bidKey": "GEM/2026/B/7605377",
  "bidId": "GEM/2026/B/7605377",
  "rating": 5,
  "rationale": "Strong match: environmental test chamber + data acquisition…",
  "method": "model",
  "eliminatedBy": null,
  "autoRejected": false,
  "userState": "new",
  "bidStatus": "OPEN",
  "hasRestrictiveEligibility": true,
  "overview": {
    "title": "Supply & Installation of Environmental Test Chamber",
    "buyer": "ISRO Propulsion Complex",
    "ministry": "Department of Space",
    "department": "Quality & Reliability",
    "location": "Mahendragiri, Tamil Nadu",
    "value": "₹1,80,00,000",
    "openingDateRaw": "2026-05-20",
    "closingDate": "2026-06-13T17:00:00Z",
    "closingDateRaw": "2026-06-13T17:00:00Z"
  },
  "summary": {
    "available": true,
    "status": "ok",
    "markdown": "## Project Description\n…server-rendered markdown…",
    "coverage": "full",
    "unparsedDocuments": ["legacy_annexure.doc"],
    "model": "claude-sonnet-4-6",
    "generatedAt": "2026-06-06T04:12:00Z"
  }
}
```

Field notes for the UI:
- **AI Evaluation** (always): `rating` (digit, no star), `rationale`. Filtered → rating 0 +
  "Filtered" badge + `eliminatedBy`.
- **AI Summary**: if `summary.available` → render `summary.markdown` (Tier A). Else show
  **Generate Summary** (Tier B), **disabled when `bidStatus:"CLOSED"`**.
- `hasRestrictiveEligibility:true` → prominent go/no-go flag (WEBAPP_DESIGN §7.5,
  `target-bid-detail-restrictive-eligibility`).
- `summary.unparsedDocuments` non-empty → "⚠ Some documents could not be read" notice with the
  filenames (WEBAPP_DESIGN §4 / §7). `summary.coverage:"partial"` → note the summary may be partial.
- `overview` fields that don't exist for a portal are `null` — render only the present ones.
- `bidStatus` ∈ `OPEN | EXTENDED | CLOSED`.

### `POST /api/portals/{portal}/bids/{bidKey}/generate-summary`
On-demand Pass 2 (Tier B). No body. Behind a global lock.
- `200` → the **same `summary` object** as above (`available:true`, rendered `markdown`).
- `409 summarization_busy` → "Summarization is busy (nightly run in progress). Try again shortly."
- `422 bid_closed` → bid is CLOSED (the button should already be disabled).
May take seconds to a minute (real Sonnet call) — show a spinner.

### `POST /api/portals/{portal}/bids/{bidKey}/disposition`
Accept / Reject a **model-scored** bid (WEBAPP_DESIGN §7.6). Request:
`{ "action": "accepted" | "rejected" }`
- `200` → `{ "userState": "accepted" }`. Also writes the activity log (§6 below).
- Shown while `userState:"new"`. (Filtered bids are dispositioned via Notifications, not here.)

---

## 5. Notifications (auto-filtered review)

The **queue is shared & live** — it shrinks as *any* teammate disputes/accepts, so re-fetch on
panel open and tolerate items disappearing. The **red dot is per-user**.
Example: [`fixtures/notifications.json`](fixtures/notifications.json).

### `GET /api/notifications/auto-filtered`
`200` → `{ "items": [ … ], "total": 7 }`, each item:
```json
{
  "portal": "gem",
  "bidKey": "GEM/2026/B/9001233",
  "bidId": "GEM/2026/B/9001233",
  "description": "Supply of A4 copier paper and toner cartridges",
  "matchedKeyword": "toner cartridges",
  "closingDateRaw": "2026-06-18",
  "firstSeen": "2026-06-06T03:40:00Z"
}
```

### `GET /api/notifications/auto-filtered/count`
`200` → `{ "count": 7 }` — **per-user new** count (bids filtered since *you* last opened the panel).
Drives the red dot.

### `POST /api/notifications/auto-filtered/viewed`
`204`. Marks the panel seen for the current user → clears the **red dot only**, not the queue.

### `POST /api/notifications/auto-filtered/save-all`
`200` → `{ "accepted": 7 }`. Accepts every queued auto-filtered bid (clears the queue).

### `POST /api/notifications/auto-filtered/{portal}/{bidKey}/dispute`
Request: `{ "reason": "This is a test rig, in-scope" }`
- `200` → `{ "disputed": true }`. Promotes the bid (requeues it for scoring) and logs `disputed`.

---

## 6. Activity log

### `GET /api/activity`
Paginated team action feed (WEBAPP_DESIGN §9). `?page&pageSize`.
Example: [`fixtures/activity.json`](fixtures/activity.json).
```json
{
  "items": [
    { "id": 412, "user": "karthikeyan@teclever.com", "portal": "gem",
      "bidId": "GEM/2026/B/7605377", "action": "accepted",
      "detail": null, "createdAt": "2026-06-06T09:14:00Z" }
  ],
  "page": 1, "pageSize": 50, "total": 137
}
```
`action` ∈ `accepted | rejected | disputed`; `detail` carries the dispute reason for `disputed`,
else `null`. Append-only — a bid can appear multiple times.

---

## 7. System alert banner (optional surface)

### `GET /api/system-alert`
`200` → `null` when clear, or `{ "id": 3, "reason": "GeM stage failed", "raisedAt": "…" }` when a
nightly cycle failed (sticky). `POST /api/system-alert/{id}/clear` → `204` (user-attributed clear).
See WEBAPP_DESIGN WEBAPP_HANDOFF §7. Lowest priority — build last.

---

## 8. Endpoint → fixture map

| Endpoint | Fixture |
|----------|---------|
| `GET /api/auth/me` | `fixtures/auth-me.json` |
| `GET /api/portals/gem/stats` | `fixtures/portal-gem-stats.json` |
| `GET /api/portals/gem/bids` | `fixtures/portal-gem-bids.json` |
| `GET /api/portals/gem/bids/{key}` (score 5) | `fixtures/bid-detail-score5.json` |
| `GET /api/portals/gem/bids/{key}` (filtered) | `fixtures/bid-detail-filtered.json` |
| `GET /api/notifications/auto-filtered` | `fixtures/notifications.json` |
| `GET /api/activity` | `fixtures/activity.json` |

Point a mock (MSW, json-server, or a Vite dev middleware) at these to build the full UI offline,
then flip `VITE_API_BASE` to the real server. See [`BUILD.md`](BUILD.md).

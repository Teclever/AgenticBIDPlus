# BUILD.md — Front-end build guide (zero-context start)

You are building the **front-end** of the Teclever Bid Intelligence Platform. You do **not** need
to know how the backend scrapes or scores bids — you consume a defined HTTP API. Everything you
need is in this package plus the visual reference app.

## What you are given (the handoff bundle)

This is a **two-folder** handoff — both must travel together:

| Folder | Role |
|--------|------|
| `webapp-design/` (this folder) | **The spec.** Read [`WEBAPP_DESIGN.md`](WEBAPP_DESIGN.md) end-to-end first — product, screens, behaviour, copy. Then [`API.md`](API.md) (the API contract) and [`fixtures/`](fixtures/) (mockable sample responses). `screenshots/` (40 PNGs) + `mockups/` (10 HTML wireframes) are the visual truth. |
| `UIReference/Teclever Bid intelligence/` | **The visual + component foundation.** A runnable Vite + React + React Router + Tailwind 4 + shadcn/Radix prototype: theme, component library, layout shell, Teclever logo. Look-and-feel only; **behaviour/copy in `WEBAPP_DESIGN.md` overrides the prototype.** |

> If you only received `webapp-design/`, ask for `UIReference/` — the theme, components and logo
> live there.

## What you are NOT building

- The backend / API server (built separately, in-repo: Python + FastAPI). You build against
  [`API.md`](API.md) and mock it with [`fixtures/`](fixtures/).
- Auth backend, scoring, summarization, scrapers, eliminator. The API exposes all of it.
- Anything in [`WEBAPP_DESIGN.md`](WEBAPP_DESIGN.md) §12 non-goals: forgot-password, roles, admin,
  chatbot, tender-doc list, vector/RAG, eliminator Excel UI, email.

## Stack (inherit from UIReference)

Vite · React · React Router · Tailwind 4 · shadcn/Radix · TypeScript. Reuse the reference's
theme (`UIReference/.../src/styles/theme.css`) and components (Button, modal, table, badges,
search, filter chips, portal cards, layout shell). Drop: chat, document list, star rating,
forgot-password (WEBAPP_DESIGN §10.4).

## Routes (WEBAPP_DESIGN §3.1)

`/login` · `/` (dashboard) · `/portal/:portalId` (`gem|hal|isro`) · `/portal/:portalId/bid/:bidKey`
· `/activity`. All except `/login` require auth (a `401` from any call → redirect to `/login`).

## Recommended approach

1. **Read** `WEBAPP_DESIGN.md` (esp. §3–§9, §13 reference→target checklist) and `API.md`.
2. **Stand up a mock API** from `fixtures/` so you can build the whole UI before the real server
   exists. Use **MSW** (Mock Service Worker) or a tiny dev middleware — map each endpoint in
   `API.md §8` to its fixture. Keep the mock behind `VITE_API_BASE` so flipping to the real
   server is one env change.
3. **Build screens** to the `target-*` mockups/screenshots (these are the net-new UI beyond the
   prototype): login changes, dashboard "Bids Closing By" + "All Bids", applied-filter banner,
   "Filtered" badge, single-column bid detail (no sidebar), Generate Summary button, notification
   panel + dispute modal. The `target-*.html` files in `mockups/` are standalone — open them in a
   browser.
4. **Wire to the real API** by pointing `VITE_API_BASE` at the FastAPI server. Send
   `credentials: "include"` on every request (cookie session).

## Things easy to get wrong (read these)

- **Filtered bids are shown, never hidden** — rating 0 + "Filtered" badge + `eliminatedBy`
  sub-line (WEBAPP_DESIGN §3, §6.5). They are not dropped from lists or counts.
- **`bidKey` is URL-encoded in paths**; HAL's is composite (`tender_number|line_number`). See
  `API.md §0`. Don't assume a flat numeric id.
- **Generate Summary** can return `409 summarization_busy` → show "busy, try again shortly", not a
  generic error. Disable the button when `bidStatus:"CLOSED"`.
- **Notification queue is shared & live** — it shrinks as teammates act; the **red dot is
  per-user**. Opening the panel clears the dot (POST `/viewed`), not the list (`API.md §5`).
- **Summary is server-rendered markdown** (`summary.markdown`) — render it; don't try to
  reconstruct it from raw fields. But `hasRestrictiveEligibility` and `summary.unparsedDocuments`
  are **separate top-level flags** to surface prominently (WEBAPP_DESIGN §4, §7.5).
- **Closing window = today + 7 calendar days**; the dashboard shows the literal date from
  `stats.windowDate` (`API.md §2`).
- **Responsive:** desktop tables, mobile cards (WEBAPP_DESIGN §10.2; see `27`, `28`, mobile shots).

## Done = matches the spec

Work through `WEBAPP_DESIGN.md §13` (reference → target checklist). Each row is a screen whose
target screenshot you must match, with the behaviour in the surrounding section and the data from
`API.md`.

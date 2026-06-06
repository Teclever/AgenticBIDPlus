# fixtures/ — mockable sample API responses

Static JSON matching the shapes in [`../API.md`](../API.md). Point a mock (MSW, json-server, or a
Vite dev middleware) at these so the whole UI can be built before the real FastAPI server exists,
then flip `VITE_API_BASE` to the real server.

| File | Endpoint |
|------|----------|
| `auth-me.json` | `GET /api/auth/me` |
| `portal-gem-stats.json` | `GET /api/portals/gem/stats` |
| `portal-gem-bids.json` | `GET /api/portals/gem/bids` (mixed: score 5/4/3/2, a CLOSED, a filtered) |
| `bid-detail-score5.json` | `GET /api/portals/gem/bids/{key}` — stored summary + restrictive eligibility + an unreadable doc |
| `bid-detail-filtered.json` | `GET /api/portals/gem/bids/{key}` — eliminated bid (rating 0, `method:"keyword"`) |
| `notifications.json` | `GET /api/notifications/auto-filtered` — incl. a HAL composite `bidKey` |
| `activity.json` | `GET /api/activity` — accepted / rejected / disputed rows |

These are **representative**, not exhaustive — cover every state from `WEBAPP_DESIGN.md` by
varying the fields (`rating`, `method`, `userState`, `bidStatus`, `summaryAvailable`,
`hasRestrictiveEligibility`). The data is synthetic.

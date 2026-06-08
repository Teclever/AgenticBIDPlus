# Teclever Bid Intelligence — Design Package

Authoritative web application design for the Bid Analysis Portal.

## Contents

| Path | Purpose |
|------|---------|
| [`WEBAPP_DESIGN.md`](WEBAPP_DESIGN.md) | Full product spec — UX, behaviour, screenshot references; §16 = backend/API decisions |
| [`BUILD.md`](BUILD.md) | **Start here if you're the front-end agent** — zero-context build guide |
| [`API.md`](API.md) | Front-end API contract — every endpoint with request/response shapes |
| [`fixtures/`](fixtures/) | Mockable sample API responses (build the UI offline, then flip to the real server) |
| [`screenshots/`](screenshots/) | 40 PNG captures (reference prototype + target wireframes) |
| [`mockups/`](mockups/) | HTML wireframes for UI not yet in the prototype |
| [`scripts/capture-screenshots.mjs`](scripts/capture-screenshots.mjs) | Regenerate screenshots |

## Handoff note

This package is a **front-end** handoff: the API layer is built **separately in this repo**
(Python + FastAPI). A fresh front-end agent needs **this folder + the `UIReference/` app**
(see `BUILD.md`). The folder alone is a spec, not a runnable app.

## Regenerate screenshots

1. Start the reference UI: `cd "../frontend" && npm run dev`
2. From this folder: `node scripts/capture-screenshots.mjs`

## Interactive prototype

The runnable reference app lives at [`../frontend/`](../frontend/). Behaviour in `WEBAPP_DESIGN.md` overrides the prototype where they differ.

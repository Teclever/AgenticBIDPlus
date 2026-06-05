# DEPLOY_WORKFLOW.md — Teclever Bid Analysis Portal

**Standalone deploy + remote-test runbook.** This document is **self-contained and
agent-executable**: an agent given *only this file* and the connection facts in §1 can
provision the deploy box, ship a new build, and verify it — without reading the design
plan. It does **not** describe how the software is built (see `MASTER_ACTION_PLAN_V3.md`
for that); it describes how a built, committed change gets onto the deploy box and proven.

**Operating model (fixed decisions):**
- **Deploy-once cadence.** This system is **deployed once and left running**; it is revisited only on a **major issue** (most likely a portal changing its markup, which forces a tool rework). There is **no continuous-delivery loop**. The durable, always-used parts of this doc are **§2 (one-time provisioning)** and the **guards** (§3.1) + **safety property** (§3.2). The lane/smoke/rollback machinery in **§4–§6 is optional and over-built for this cadence** — kept as reference for *if* the cadence ever increases, but the **canonical redeploy is the lean procedure in §3.0 below**.
- **Agent lives on the Mac dev machine.** It drives the Ubuntu deploy box **over SSH on
  the same LAN** — no VPN/overlay, no port-forwarding.
- **Deployment is always a git pull on the box.** Never rsync, never scp of source. The
  box checks out a commit; runtime state and secrets are never shipped (they're gitignored).
- **The deploy box is a deploy-phase dependency, not a build-phase one.** All slices
  (S0–S7) are built and validated on the Mac. This workflow only runs once the box is
  reachable; nothing here blocks development.
- **Forward-looking (optional):** lanes for the React frontend and the middleware are
  sketched in §4 for *if* they ever land — but per the deploy-once cadence they are **not a
  current deliverable** and need not be wired now.

---

## 1 · Connection & access facts (the shared information)

Everything an agent needs to reach and act on the box. **Values marked `‹FILL IN›` are not
yet known and must be supplied before first deploy.** Known values are from `ServerSpec.txt`
and `MASTER_ACTION_PLAN_V3.md` decisions #18/#19.

| Fact | Value | Notes |
|---|---|---|
| **SSH user@host** | `congo@tecleverbidplus` | LAN hostname; resolves via mDNS/`.local` or `/etc/hosts`. If mDNS is flaky, pin the LAN IP. |
| **SSH LAN IP** | `‹FILL IN›` | Static/DHCP-reserved IPv4 on the LAN. Prefer reserving it on the router. |
| **SSH auth** | key-based, no password | Mac's public key in the box's `~/.ssh/authorized_keys`. `PasswordAuthentication no` recommended. |
| **SSH alias** | `bidbox` (suggested) | Add to `~/.ssh/config` on the Mac so every command is `ssh bidbox '…'`. See §1.1. |
| **Git remote (origin)** | `‹FILL IN›` | The URL the box pulls from. Same-LAN options in §1.2. The box's clone has this as `origin`. |
| **Deploy branch** | `main` | The box only ever checks out commits reachable from this branch (or an explicit SHA/tag). |
| **Repo root on box** | `/home/congo/BidAnalysisPortal/` | The git working tree. (#18) |
| **Runtime root on box** | `/home/congo/bidplus-runtime/` | `BIDPLUS_RUNTIME_DIR`. Holds venv, `.env`, per-portal DBs, `bids/<pk>/` staging, `exports/`. Never in git. (#19) |
| **venv on box** | `/home/congo/bidplus-runtime/venv/` | All Python runs as `…/venv/bin/python`. |
| **Secrets file** | `/home/congo/bidplus-runtime/.env` | Holds the single `ANTHROPIC_API_KEY`. **Provisioned once by a human; never shipped, never overwritten.** (#19/§4) |
| **Deployed-SHA marker** | `git rev-parse HEAD` in repo root | The source of truth for "what's deployed now." Used as the diff base. No separate file needed. |
| **systemd unit (orchestrator)** | `bidplus.service` + `bidplus.timer` | ~3am nightly cycle. (#27/§4) |
| **systemd unit (middleware, future)** | `bidplus-api.service` | Activated when the middleware lane first deploys. |
| **OS / hardware** | Ubuntu 24.04, i3-7100U, 7.6 GB RAM, 4 GB swap | Low-spec — keep redeploy verification to the single real run in §3.0. |
| **Root LV capacity** | ~100 GB at `/` (828 GB unallocated in `ubuntu-vg`) | See §2 provisioning for optional `lvextend`. The ~14 GB working set fits 100 GB. |

### 1.1 Suggested `~/.ssh/config` on the Mac
```sshconfig
Host bidbox
    HostName tecleverbidplus      # or the reserved LAN IP from §1
    User congo
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 30
```
After this, every command in this doc is `ssh bidbox '…'`.

### 1.2 Git access on a same-LAN setup
"Deployment is a git pull on the box" requires the box to have an `origin` it can fetch.
Pick one (all compatible with this runbook — only the `origin` URL differs):
- **External host (GitHub/GitLab):** box pulls over HTTPS (deploy token) or SSH (deploy
  key). Simplest if the box has outbound internet (it does — NAT'd broadband).
- **Mac as the remote (no external host):** the Mac hosts a bare repo or serves the working
  repo over SSH; the box's `origin` is `congo-mac@<mac-lan-ip>:…`. Keeps everything on the
  LAN. Requires the Mac reachable when deploying (it is — same LAN, and the agent runs there).

Whichever is chosen, record the final URL in the §1 table and ensure
`ssh bidbox 'cd /home/congo/BidAnalysisPortal && git fetch origin'` succeeds non-interactively.

---

## 2 · One-time provisioning (deploy-box bring-up)

Run **once**, when the box is first made available. Tracked checklist — an agent ticks each
and records the result. Order matters where noted.

- [ ] **SSH reachability** — `ssh bidbox 'echo ok'` returns `ok` non-interactively (key auth,
      no password prompt). *Gate: nothing else proceeds until this passes.*
- [ ] **System packages** — `git`, `python3.12`, `python3.12-venv`, build essentials present.
- [ ] **(Optional) Expand the root LV** — only if the ~100 GB root is ever deemed tight.
      828 GB sits unallocated in `ubuntu-vg`. This is **operator-run, never automated**:
      ```bash
      sudo lvextend -l +100%FREE /dev/ubuntu-vg/ubuntu-lv
      sudo resize2fs /dev/ubuntu-vg/ubuntu-lv
      ```
      Default stance: **skip it** — the 14 GB working set fits 100 GB, and the strict 7-day
      sweep is the real safeguard (no high-watermark). Listed here so the headroom is known.
- [ ] **Clone the repo** — `git clone <origin> /home/congo/BidAnalysisPortal` (branch `main`).
- [ ] **Create the runtime root** — `/home/congo/bidplus-runtime/` with `gem/ hal/ isro/`,
      `exports/`, the `bids/` staging trees, and `list_review/{pending,ready,consumed}/` (the
      eliminator list-change review folders, per §5b of the plan). Set `BIDPLUS_RUNTIME_DIR`
      in the box's environment (e.g. the systemd unit's `Environment=` and an interactive
      `~/.profile` export).
- [ ] **Create the venv** — `python3.12 -m venv /home/congo/bidplus-runtime/venv` and
      `…/venv/bin/pip install -r /home/congo/BidAnalysisPortal/bidplus/requirements.txt`.
- [ ] **Provision secrets** — create `/home/congo/bidplus-runtime/.env` with the single
      `ANTHROPIC_API_KEY`. **Human-entered once.** Confirm it is **outside** the git tree and
      mode `600`. This file is never shipped and never overwritten by a deploy.
- [ ] **Playwright system deps** — **operator-run once, interactively** (needs sudo — it
      apt-installs system libraries): `sudo …/venv/bin/playwright install-deps chromium`,
      then the (no-sudo) browser fetch `…/venv/bin/playwright install chromium`. Splitting it
      keeps every *later* command non-interactive over SSH. (Ubuntu needs the system libs;
      this differs from the Mac.)
- [ ] **Prove headless Chromium works on the box** — run the trivial headless probe and
      confirm it prints a page title from the box itself (not just from the Mac dev machine).
      *This is the deploy-side counterpart to the S0 "prove headless Chromium" gate — both
      machines must pass independently.*
- [ ] **GeM TLS** — append the eMudhra CA cert to the venv's `certifi` bundle. **Do NOT set
      `REQUESTS_CA_BUNDLE`** (it breaks the Anthropic SDK). `certifi` is **pinned in
      `requirements.txt`** (plan §5) so a later `pip install` won't silently upgrade it and
      wipe this append — but if you ever *do* bump `certifi`, **re-run this append**. (§4 of
      the plan.)
- [ ] **Install systemd units** — copy `deploy/systemd/bidplus.service` + `bidplus.timer`
      (shipped in the repo, ~3am) to `/etc/systemd/system/`, `systemctl daemon-reload`, then
      `systemctl enable --now bidplus.timer`. Confirm `systemctl list-timers` shows the next
      fire. The service runs `python -m bidplus.launcher run` (the full sequential cycle:
      scrape → Pass 1 → merge → tiered gate, writing `scrape_runs` + sticky `system_alerts`).
- [ ] **Seed the eliminator lists (FIRST DEPLOY ONLY)** — load the mined seeds shipped in
      `bidplus/data/` into the `eliminator_terms` table: `eliminator_keywords.json` (689
      negative) + `inscope_signals.json` (237 positive), all `source='mined'`. This is a
      **one-time** seed; thereafter the table is the source of truth and changes **only** via
      the Excel governance loop (drop reviewed files in `list_review/ready/`; ingested at the
      next run). See plan §32 / `ELIMINATOR_DESIGN.md` §5. *(Idempotent: re-running the seed on
      an already-populated table is a no-op — it must NOT clobber governance-applied changes.)*
- [ ] **First real orchestration** — run the orchestrator once end-to-end (or wait for the
      nightly); confirm `scrape_runs` rows are written, paths resolve under the runtime root,
      and a sample `summary_json` looks sane. (No dry-run/fixture mode exists — verification is
      this manual single-run eyeball, per plan §9 non-goals and §3.0.)
- [ ] **Record baseline** — capture `git rev-parse HEAD` as the first deployed SHA.

When every box is ticked, the box is live. For ongoing changes, the **canonical path is the
lean §3.0 redeploy**; the full pipeline (§3 loop + §4–§6) is optional reference.

---

## 3 · Redeploy

### 3.0 Canonical redeploy (deploy-once cadence — use this)

A redeploy happens rarely (a portal broke and a tool was reworked, or a real fix). It is a
short, **manual, agent-assisted** procedure — not a pipeline:

```
1. GUARD     ssh bidbox 'echo ok'      (reachable?)   AND   not in 02:30–09:30
                                                       AND   no live run (finished_at IS NULL)
2. RECORD    CUR = ssh bidbox 'git -C <repo> rev-parse HEAD'     (rollback target)
3. APPLY     ssh bidbox 'git -C <repo> fetch origin &&
                          git -C <repo> reset --hard <NEW-sha>'   (clean, no dirty-tree risk)
4. DEPS      if requirements changed → '…/venv/bin/pip install -r bidplus/requirements.txt'
             (if Playwright pinning changed → re-run the operator Playwright step, §2)
5. RESTART   ssh bidbox 'systemctl restart bidplus.service'   (timer unaffected unless unit changed)
6. VERIFY    run the orchestrator ONCE (or wait for the nightly) → eyeball scrape_runs
             (status, counts) + one sample summary_json. Migrations auto-apply on start (§3.3).
7. DONE      record NEW as deployed. If step 6 looks wrong → ROLLBACK: reset --hard CUR, restart.
```

That is the whole redeploy. No lane routing, no automated smoke suite — at this cadence,
**manual eyeballing of one real run is the verification.**

### 3.1 Guards (always apply, even for the lean path)
- **Reachability:** `ssh bidbox 'echo ok'`. Abort cleanly if unreachable.
- **Overnight-window guard:** refuse to deploy/restart between **02:30 and 09:30** local, the
  window the nightly cycle owns. A restart mid-run risks SQLite/WAL corruption.
- **Active-run guard:** refuse if a run is in progress — detected as a `scrape_runs` row with
  **`finished_at IS NULL`** (the orchestrator inserts an in-progress row at start; plan S4).
  Cheap check: `ssh bidbox '…/venv/bin/python -m bidplus.cli run-status'` (or a `SELECT`).
  Belt-and-suspenders with the time window.
- **Clean-tree:** the box is pull-only and must never carry local source edits. The lean path
  uses `git reset --hard <sha>` (and you may assert `git status --porcelain` is empty first),
  so a stray tracked-file edit can't make the checkout fail or silently persist.

### 3.3 Schema migrations on redeploy
The parent DB is runtime state — `git checkout`/`reset` never touches it. Schema changes ship
as **additive `_migrate()` ALTER TABLEs that auto-apply on orchestrator start**, so a redeploy
that adds a column just needs the **service restart** (step 5) to take effect. No manual
migration step.

---

## 3-opt · Full deploy loop *(OPTIONAL — over-built for deploy-once; reference only)*

> Kept for *if* the cadence ever becomes frequent (e.g. active web-app development). At the
> current deploy-once cadence, use §3.0 instead — you do not need the lane table, the
> automated smoke harness, or rollback orchestration below.

A deploy is a deterministic pipeline the agent runs from the Mac. No daemon, no webhook —
it is **agent-invoked** (you ask for a deploy, or a scheduled agent run triggers it).

```
1. PRE-CHECK   reachable? not inside the overnight window? no run in progress?
2. RESOLVE     NEW  = target SHA (tip of `main`, or an explicit SHA/tag)
               CUR  = ssh bidbox 'git -C <repo> rev-parse HEAD'      (deployed SHA)
3. DIFF        changed = git diff --name-only CUR NEW
4. ROUTE       map changed paths → active lanes (§4 table). No match in a lane ⇒ skip it.
5. APPLY       ssh bidbox 'git -C <repo> fetch origin && git reset --hard NEW'
6. LANE STEPS  for each active lane, run its deploy action (§4)
7. SMOKE       for each active lane, run its smoke test (§4 contracts) — fast, dry-run
8. VERDICT     all green ⇒ record NEW as deployed; report. Any red ⇒ ROLLBACK (§6) + report
```

### 3.2 Why git checkout/reset is safe for secrets/data
`.env`, `*.db`/`-wal`/`-shm`, `downloads/`, `exports/`, `.browser_profile/` are gitignored,
and all runtime state — including the `bids/<pk>/` document staging — lives under the
**runtime root** (`$BIDPLUS_RUNTIME_DIR`), **not the git tree**. `git checkout`/`reset --hard`
touches only tracked source, so it **physically cannot** clobber secrets, databases, or
staged documents. This property is the reason the model is git-pull and not file-sync.

---

## 4 · Component routing table (all lanes) *(OPTIONAL — frequent-cadence reference)*

> **Not used at the current deploy-once cadence** — the lean §3.0 redeploy covers it. This
> table only earns its keep if you start shipping changes often. The scraper/summarizer smoke
> tests below also depend on `--dry-run`/fixture and stubbed-Sonnet modes that the plan
> explicitly **does not build** (plan §9 non-goals); they'd be a prerequisite to activate.

The agent matches `git diff --name-only` against these globs. Only matched lanes run. Lanes
whose paths don't exist yet are simply never matched until that code lands — the table is
forward-complete.

| Lane | Trigger paths (globs) | Deploy action on box | Smoke test (target: seconds) |
|---|---|---|---|
| **Deps / runtime** | `requirements*.txt`, `pyproject.toml`, anything Playwright-pinning | `…/venv/bin/pip install -r bidplus/requirements.txt`; if Playwright changed → operator re-runs the §2 Playwright step | venv imports clean; headless Chromium launch probe prints a title |
| **Scrapers** | `gem_portal/**`, `hal_portal/**`, `isro_portal/**` | (pure Python — no build step) | per changed portal: **1-bid dry run** (fixture/`--dry-run`, no live portal hit) → exit 0 + expected parsed fields / DB row |
| **Orchestrator** | `bidplus/**` | `systemctl restart bidplus.service` if running; reload timer if unit changed | **dry orchestration** (no live scrape) → `scrape_runs` row written, gate buckets sane, exit 0 |
| **Summarization** | `bidplus/summarize*`, `bidplus/extract*` | (covered by orchestrator restart) | run §8b module on a **fixture bid** → Pydantic-valid `summary_json`, **no live Sonnet call** (stubbed/recorded response) |
| **Middleware** *(future)* | `middleware/**`, `api/**` | `systemctl restart bidplus-api.service` | `curl -fsS localhost:<port>/health` → 200 |
| **Frontend** *(future)* | `frontend/**` | `npm ci && npm run build` (in box's frontend dir); publish build artifacts | `curl -fsS localhost:<port>/` → 200; built `index.html` present |
| **Systemd units** | `deploy/systemd/**`, `*.service`, `*.timer` | copy units → `systemctl daemon-reload` → re-enable | `systemctl is-enabled bidplus.timer` = enabled; next fire listed |
| **Provisioning/docs** | `DEPLOY_WORKFLOW.md`, `deploy/**` non-unit, `*.md` | none (informational) | none |

**Budget discipline (the box is an i3 / 7.6 GB):** smoke tests are *smoke*, not the suite.
Each lane's check targets seconds — low minutes at worst. Full data runs stay on the nightly
timer; never trigger a live multi-portal scrape from a deploy. Unchanged lanes don't run, so a
docs-only or frontend-only deploy never rebuilds the Python world.

---

## 5 · Smoke-test contracts *(OPTIONAL — only if §4 lanes are activated)*

> Per the deploy-once cadence and plan §9 non-goals, **these modes are not being built.**
> Verification is the manual single-run eyeball in §3.0. The contracts below apply only if a
> future frequent-cadence setup activates §4.

Each lane's smoke test must be runnable **non-interactively over SSH** and must **not touch
live external services**. Activating them would require building two modes (which the plan
currently de-scopes):

- **`--dry-run` / fixture mode** for each scraper: parses a bundled saved page instead of
  hitting the portal; asserts the parser still yields sane fields. No live HAL/ISRO/GeM call
  (avoids rate-limits/bans on every deploy).
- **Recorded/stubbed Sonnet response** for the summarization smoke: exercises the
  extract→assemble→Pydantic-validate path against a canned API response. No live token spend.

A smoke test's **contract** is a single exit code plus a one-line machine-readable result the
agent can parse (e.g. `SMOKE scrapers/gem OK rows=1` / `SMOKE orchestrator FAIL <reason>`).
Green = exit 0 and the expected assertion line. Anything else = red.

---

## 6 · Guards, rollback, and reporting

- **Rollback is a checkout.** If a redeploy's single run (§3.0 step 6) looks wrong:
  `ssh bidbox 'git -C <repo> reset --hard CUR'`, restart the service against `CUR`, confirm
  it's healthy, and report. The deployed-SHA marker stays at `CUR`. Because deploys are
  commit-atomic and data lives outside the tree, rollback is clean and instant.
- **Never overwrite `.env` or any runtime data.** Restated because it's the highest-cost
  mistake. Deploy = checkout/reset of tracked source only.
- **Lock against the nightly cycle** (§3.1) — both the time window and the active-run check
  (`finished_at IS NULL`).
- **Report** every redeploy: target SHA, what changed, the §3.0 verify result, final verdict
  (deployed / rolled back), and the new deployed SHA. This report is the audit trail.

---

## 7 · Agent operating procedure (the short version)

1. Confirm §1 facts are filled in; if first ever run, complete §2 provisioning.
2. Run the **§3.0 lean redeploy**: guard → record CUR → `reset --hard NEW` → (deps if changed)
   → restart → run once + eyeball `scrape_runs` + a sample summary.
3. Looks right ⇒ record NEW as deployed, emit the §6 report. Looks wrong ⇒ `reset --hard CUR`,
   restart, emit the report with the reason. **Do not leave the box in a half-deployed state.**
   *(The §3-opt pipeline + §4–§6 lanes are optional, for a future frequent cadence only.)*

### Hard "never" list
- Never deploy or restart inside the 02:30–09:30 overnight window, or while a run is active
  (`finished_at IS NULL`).
- Never ship source by rsync/scp; never put runtime state or secrets in git.
- Never overwrite the box's `.env` or its databases.
- Never run a live multi-portal scrape or a live billed Sonnet call as a smoke test.
- Never run `lvextend`/`resize2fs` automatically — operator-only, opt-in.

---

## 8 · Open items (fill before first deploy)

- [ ] Box LAN IP (and router DHCP reservation) — §1.
- [ ] `origin` URL + access method (external host vs Mac-as-remote) — §1.2.
- [ ] Confirm Mac→box SSH key auth works non-interactively — §2.
- [ ] Decide the redeploy trigger (manual when something breaks — the expected case — vs a
      scheduled agent run).
- *(Dropped: `--dry-run`/fixture + stubbed-Sonnet entry points. Per the deploy-once cadence
  and plan §9 non-goals, the automated smoke harness is not built; verification is the manual
  §3.0 single-run eyeball.)*

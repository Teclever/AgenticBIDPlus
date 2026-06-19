# bidplus.control — Control-Plane Agent

## Purpose

`bidplus.control` is a long-running agent that bridges an operator-controlled Google Sheet
and the on-box scrapers.  The box (`tecleverbidplus`) is outbound-only — it cannot be reached
directly.  The Sheet is the rendezvous: operators queue commands there, the agent picks them
up, runs the appropriate launcher, and writes results back.  The agent reports facts only
(scores, titles, portal pass/fail counts); it never makes recommendations.

Start with:

    python -m bidplus.control

---

## Environment Variables

All configuration is via env vars.  `control.env` (the systemd `EnvironmentFile`) is the
canonical place to set them on the box.

| Variable | Required? | Default | Meaning |
|---|---|---|---|
| `BIDPLUS_CONTROL_SHEET_ID` | **YES** | _(none — agent refuses to start without it)_ | Google Spreadsheet ID (the long hash in the Sheet URL) |
| `BIDPLUS_CONTROL_SA_KEY` | no | `/etc/bidplus/bidplus-control-1b58558711e0.json` | Path to the service-account JSON key file |
| `BIDPLUS_CONTROL_POLL_SECS` | no | `60` | How often (seconds) the agent polls the `Commands` tab |
| `BIDPLUS_CONTROL_BID_TABS_KEEP` | no | `14` | Number of dated bid-list tabs to retain before pruning older ones |
| `BIDPLUS_CONTROL_WORKER` | no | `hostname` | Worker identity written to Status and Runs tabs |
| `BIDPLUS_CONTROL_STATE_DIR` | no | `<BIDPLUS_RUNTIME_DIR>/control` | Directory for local state file and per-run logs |
| `BIDPLUS_RUNTIME_DIR` | no | `~/bidplus-runtime` → `/home/congo/bidplus-runtime` | Runtime root (shared with main scraper; sets parent.db path etc.) |

---

## control.env — EnvironmentFile Example

Create `/home/congo/bidplus-runtime/control.env` (mode 600, owned by congo):

```
# REQUIRED — replace with your actual spreadsheet ID
BIDPLUS_CONTROL_SHEET_ID=1AbCdEfGhIjKlMnOpQrStUvWxYz_your_sheet_id_here

# SA key path defaults correctly for the box; uncomment only if different
# BIDPLUS_CONTROL_SA_KEY=/etc/bidplus/bidplus-control-1b58558711e0.json

# Optional tuning
# BIDPLUS_CONTROL_POLL_SECS=60
# BIDPLUS_CONTROL_BID_TABS_KEEP=14
```

---

## Google Sheet Structure

The spreadsheet has four types of tabs:

### Fixed tabs

| Tab | Purpose |
|---|---|
| `Status` | Live snapshot — overwritten every poll tick.  Contains heartbeat timestamp, worker identity, current command (if any), portal pass/fail counts from the last run. |
| `Runs` | Append-only cycle history — one row per completed run/rerun with start time, end time, exit status, portal summary. |
| `Commands` | Operator input — add a row here to queue a command (see below). |

### Dated bid-list tabs

One tab is created per run/rerun.  Naming conventions:

| Event | Tab name |
|---|---|
| Nightly full cycle | `Nightly YYYY-MM-DD` |
| Manual full cycle | `Run YYYY-MM-DD HH:MM` |
| Portal rerun | `Rerun <portal> YYYY-MM-DD HH:MM` |

Tabs are sorted by score descending and have these columns:

| Column | Meaning |
|---|---|
| Bid ID | Portal-specific identifier |
| Title | Bid/tender title |
| Organization | Issuing organisation |
| Pass-1 score | Numeric relevance score from Pass-1 classifier |
| Summary | AI-generated one-paragraph summary |

Tabs older than `BIDPLUS_CONTROL_BID_TABS_KEEP` (default 14) are auto-pruned on each tick.

---

## Command Vocabulary

Only two commands are recognised:

| Command | Portal field | Maps to |
|---|---|---|
| `run` | _(leave blank)_ | `python -m bidplus.launcher run` (full cycle, all portals) |
| `rerun` | `hal` \| `halc` \| `isro` \| `gem` | `python -m bidplus.launcher run --only <portal>` |

---

## How the Operator Queues a Command

1. Open the Google Sheet and go to the **`Commands`** tab.
2. Add a new row at the bottom:
   - **`command`** column: set to `run` or `rerun`
   - **`portal`** column: for `rerun`, set to one of `hal`, `halc`, `isro`, `gem`; for `run`, leave blank
   - **`status`** column: leave blank (the agent fills this in)
3. Save / press Enter.  The agent picks it up within `BIDPLUS_CONTROL_POLL_SECS` seconds.

The agent transitions the row through these states:

    (blank) → pending → running → done
                                → failed
                                → interrupted  (if service was restarted mid-run)

A `result` cell is written when the command finishes.  Results also appear in a new dated
bid-list tab and in the `Status` / `Runs` tabs.

---

## Deploy Steps

Run these on the box as a user with sudo access (not as congo):

```bash
# 1. Install the new Python deps into the box venv
sudo -u congo /home/congo/bidplus-runtime/venv/bin/pip install "gspread>=6.0" "google-auth>=2.0"

# 2. Create control.env (see example above)
sudo -u congo install -m 600 /dev/null /home/congo/bidplus-runtime/control.env
sudo -u congo nano /home/congo/bidplus-runtime/control.env   # paste your SHEET_ID

# 3. Grant congo read access to the SA key (key must already be mode 600, owned bidplus:bidplus)
sudo setfacl -m u:congo:r /etc/bidplus/bidplus-control-1b58558711e0.json

# 4. Copy the unit file and enable the service
sudo cp /home/congo/BidAnalysisPortal/deploy/bidplus-control.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bidplus-control

# 5. Confirm it started cleanly
journalctl -u bidplus-control -f
```

---

## Restart-Recovery Behaviour

When systemd restarts the service (crash, manual restart, or deploy), it kills the entire
cgroup — including any in-flight `bidplus.launcher` child process.  On the next start-up the
agent reads its local state file (`$BIDPLUS_CONTROL_STATE_DIR/state.json`) and, if a command
was in the `running` state, marks it `interrupted` in the `Commands` tab (no `result` is
written).  The same command is **never** double-executed.  If the operator wants to retry,
they queue a new row in the `Commands` tab.

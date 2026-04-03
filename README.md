# derby-scoreboard-api

A lightweight REST proxy for the [CRG Scoreboard](https://github.com/rollerderby/scoreboard) WebSocket. Runs alongside the scoreboard software and re-exposes live game state as a simple HTTP endpoint — no WebSocket knowledge required.

## Why this exists

The CRG scoreboard broadcasts live data (scores, clocks, jammer info) over WebSocket. This proxy connects to that feed and makes it available as a plain `GET /live` JSON endpoint that any custom overlay or display software can poll.

## Requirements

- Python 3.10+ (3.13 recommended)
- CRG Scoreboard already installed, running, and accessible (default port 8000; host/port configurable via flags)

## Setup on Windows

### 1 — Install Python (if not already installed)

If you have [Chocolatey](https://chocolatey.org/install), open PowerShell as administrator:

```powershell
choco install python -y
```

Or download directly from [python.org](https://www.python.org/downloads/).

Verify:
```powershell
python --version
```

### 2 — Start the CRG Scoreboard

Launch the scoreboard the normal way (double-click the provided `.exe` or `.bat` file, or run `java -jar crg-scoreboard.jar`). Confirm it is accessible at `http://localhost:8000` before continuing.

### 3 — Install and start the proxy

```powershell
cd derby-scoreboard-api
pip install -r requirements.txt
python main.py
```

The API is now available at `http://localhost:5001`.

## One-click update for non-technical users (Windows)

To update with minimal interruption, this repo includes:

- `updater.config.json` (single config file to choose update mode and settings)
- `Run-Updater.cmd` (double-click entry point that reads config and picks mode)
- `scripts/` (all automation scripts — you can ignore these)

For non-technical users, this is the only workflow you need:

1. Open `updater.config.json`
2. Set `mode` to `manual` or `auto`
3. Double-click `Run-Updater.cmd`

What it does:

1. Runs `git pull --ff-only`
2. Installs Python dependencies from `requirements.txt`
3. Starts a standby API backend on an alternate port
4. Swaps the stable proxy target to the healthy standby backend
5. Stops the old backend after cutover
6. Writes logs to `logs/updater/`

### Blue/green ports

- Public API (stable): `5001` via `proxy.py`
- Backend A: `5002`
- Backend B: `5003`

The proxy reads `runtime/active_backend_port.txt` and forwards requests to whichever backend port is currently active.

### Setup (one-time)

1. Ensure `git`, `python`, and `pip` are available in PATH.
2. Put a shortcut to `Run-Updater.cmd` on the Desktop.
3. Ensure port `5001` is free for the stable proxy listener.

On first run, the updater starts both proxy and backend processes automatically.

### Run update

Double-click `Run-Updater.cmd`.

Set `mode` in `updater.config.json`:

- `manual`: runs one blue/green update now
- `auto`: starts continuous watcher mode

Tip: keys that start with `_comment_` are just helper notes for humans and are ignored by the launcher.

After a successful manual update, the launcher prints the `Health` and `Live` URLs using the current machine hostname so you can share them with the client team.

Example config:

```json
{
  "mode": "manual",
  "branch": "main",
  "checkIntervalSeconds": 120,
  "scoreboardHost": "localhost",
  "scoreboardPort": 8000,
  "healthUrl": "http://localhost:5001/health"
}
```

Advanced (PowerShell):

```powershell
./Run-Updater.ps1
```

## Optional automatic updates from main (no button click)

If you want unattended updates, this repo includes optional tools:

- `Auto-Update-API.ps1` (in `scripts/`; watches `origin/main` and triggers `Update-API.ps1` only when new commits exist)
- `Start-AutoUpdate.cmd` replaced by `Run-Updater.cmd` with `mode: auto` in config
- `Stop-AutoUpdate.cmd` in `scripts/`; stops a running auto watcher
- `Install-AutoUpdate-Task.cmd` in `scripts/`; creates a Windows Scheduled Task that starts watcher on boot
- `Uninstall-AutoUpdate-Task.cmd` in `scripts/`; removes that task

### How auto-update works

1. Checks the local branch name (must be `main`)
2. Runs `git fetch origin main --prune`
3. Computes commits behind with `git rev-list --count HEAD..origin/main`
4. If behind > 0, runs the blue/green swap updater
5. Repeats every 120 seconds (default)

### Recommended optional mode (no Scheduled Task)

Set `"mode": "auto"` in `updater.config.json`, then either:

- double-click `Run-Updater.cmd`, or
- double-click `Start-AutoUpdate.cmd`.

When you are done, run `Stop-AutoUpdate.cmd`.

### Always-on mode (optional Scheduled Task)

Run `Install-AutoUpdate-Task.cmd` as Administrator once.

This creates task `DerbyScoreboardAPIAutoUpdate`, starts it immediately, and runs it automatically at Windows startup.

### Disable always-on scheduled mode

Run `Uninstall-AutoUpdate-Task.cmd`.

### Manual one-shot check

```powershell
./Auto-Update-API.ps1 -RunOnce
```

### Optional watcher tuning

```powershell
./Auto-Update-API.ps1 -CheckIntervalSeconds 60 -Branch main
```

Auto-updater logs are written to `logs/autoupdater/`.

### Advanced/internal scripts

All implementation scripts live in `scripts/`. Most users should ignore that folder:

- `scripts/Update-API.ps1` and `scripts/Auto-Update-API.ps1`: core blue/green and watcher logic
- `scripts/Run-Updater.ps1`: config-driven launcher called by `Run-Updater.cmd`
- `scripts/Stop-AutoUpdate.cmd`: stops a running auto watcher
- `scripts/Install-AutoUpdate-Task.cmd` / `Uninstall-AutoUpdate-Task.cmd`: optional always-on Windows task

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--scoreboard-host` | `localhost` | Hostname/IP of the CRG scoreboard |
| `--scoreboard-port` | `8000` | Port the scoreboard is running on |
| `--host` | `0.0.0.0` | Host to bind the API server to |
| `--port` | `5001` | Port to serve the API on |

**Remote scoreboard example:**
```bash
python main.py --scoreboard-host 192.168.1.50
```

## Endpoints

### `GET /live`
Clean, mapped live game state. Poll this at whatever rate suits your overlay (200ms is smooth for clocks).

```json
{
  "connected": true,
  "period": 1,
  "jam": 4,
  "jam_clock_ms": 89000,
  "period_clock_ms": 412000,
  "jam_running": true,
  "in_jam": true,
  "game_state": "Running",
  "timeout_type": null,
  "state_age_seconds": 0.1,
  "team1": {
    "name": "Home Team",
    "score": 42,
    "jam_score": 5,
    "jammer": "Speed Demon",
    "jammer_number": "88",
    "lead": true,
    "display_lead": true,
    "calloff": false,
    "lost": false,
    "star_pass": false
  },
  "team2": {
    "name": "Away Team",
    "score": 37,
    "jam_score": 0,
    "jammer": "Lightning Bolt",
    "jammer_number": "7",
    "lead": false,
    "display_lead": false,
    "calloff": false,
    "lost": false,
    "star_pass": false
  }
}
```

> **Clock note:** All `*_ms` fields are in **milliseconds**. E.g. `89000` = 1 minute 29 seconds.

> **`connected`:** `true` when the proxy has an active WebSocket connection to the scoreboard.
> If `false`, the proxy is reconnecting and `state_age_seconds` tells you how stale the data is.
> Overlays can use this to show a "RECONNECTING" indicator without a separate call to `/health`.

> **`state_age_seconds`:** Seconds since the proxy last received an update from the scoreboard.
> `null` means no update has been received yet (proxy just connected). If this grows above a few
> seconds while `connected` is `true`, the scoreboard may be frozen.

> **`timeout_type`:** Normalized timeout/review state derived from `game_state`.
> Values: `team_timeout`, `official_timeout`, `official_review`, `timeout`, or `null`.
> It is forced to `null` when `jam_running` is `true` (play resumed).

### `GET /raw`
Full flat state dict as received from the scoreboard WebSocket. Useful for discovering all available fields or debugging.

### `GET /health`
Connection status:
```json
{"connected": true, "scoreboard_version": "v5.0.0", "seconds_since_update": 0.3}
```
`seconds_since_update` is `null` until the first update is received. A large value while `connected` is `true` indicates the scoreboard may be frozen.

### `GET /docs`
Auto-generated interactive OpenAPI docs (Swagger UI).

## Resilience

The proxy is designed to **stay running no matter what**:

- If the scoreboard isn't running when the proxy starts, it will keep retrying every 2 seconds until it connects.
- If the scoreboard restarts mid-game, the proxy reconnects automatically.
- `GET /live` returns HTTP 503 while disconnected so pollers know to wait rather than display stale data.
- `GET /health` always returns, even when disconnected — use it to monitor connection state.
- Unhandled errors in any endpoint are caught and logged without killing the process.

## Extending

See [EXTENDING.md](EXTENDING.md) for a guide on adding new fields, endpoints, and more.

## Client display field crosswalk

For a client-facing summary of requested scoreboard fields, current `/live` coverage, and missing timeout/review data needed for broadcast UI, see [CLIENT_FIELD_CROSSWALK.md](CLIENT_FIELD_CROSSWALK.md).

## Running tests

```powershell
pytest
```

Tests use a mock WebSocket server — no real scoreboard needed.

## How it works

1. On startup, a background asyncio task connects to `ws://<scoreboard-host>:<scoreboard-port>/WS/`
2. Subscribes to `ScoreBoard.CurrentGame` to receive all live game state
3. Maintains an in-memory state dict, applying incremental patches as the scoreboard broadcasts them
4. `GET /live` reads from that dict and maps raw CRG key names to clean JSON fields via a declarative field map
5. Auto-reconnects with a 2-second delay on any disconnect or error

## CRG WebSocket protocol

The proxy uses the CRG scoreboard's native WebSocket API:

- **Endpoint:** `ws://host:8000/WS/`
- **Subscribe:** `{"action": "Register", "paths": ["ScoreBoard.CurrentGame"]}`
- **Updates:** `{"state": {"ScoreBoard.CurrentGame.Clock(Jam).Time": 89000, ...}}`
- A `null` value means that key was deleted/reset
- Full protocol docs available at `http://scoreboard-host:8000/documentation/wiki-snapshot.html`
- Live key browser at `http://scoreboard-host:8000/json/state.html`

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

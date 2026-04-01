# derby-scoreboard-api

A lightweight REST proxy for the [CRG Scoreboard](https://github.com/rollerderby/scoreboard) WebSocket. Runs alongside the scoreboard software and re-exposes live game state as a simple HTTP endpoint — no WebSocket knowledge required.

## Why this exists

The CRG scoreboard broadcasts live data (scores, clocks, jammer info) over WebSocket. This proxy connects to that feed and makes it available as a plain `GET /live` JSON endpoint that any custom overlay or display software can poll.

## Requirements

- Python 3.10+ (3.13 recommended)
- CRG Scoreboard running on the same machine (or accessible on the network)
- Java 11+ (for running the CRG Scoreboard)

## Setup on Windows

### 1 — Install Python (if not already installed)

Open PowerShell as administrator:

```powershell
choco install python --version=3.13.0 -y
```

Or download directly from [python.org](https://www.python.org/downloads/).

Verify:
```powershell
python --version
```

### 2 — Install Java (required to run the CRG Scoreboard)

```powershell
choco install temurin21 -y
```

Or download from [adoptium.net](https://adoptium.net/).

Verify:
```powershell
java -version
```

### 3 — Build and start the CRG Scoreboard

From the scoreboard repo directory:

```powershell
# Download Ant (one-time) if you don't have it:
choco install ant -y

# Build the jar
ant compile

# Start the scoreboard (runs on port 8000)
java -jar lib\crg-scoreboard.jar
```

Open `http://localhost:8000` in a browser to confirm it's running.

### 4 — Install and start the proxy

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
  "period": 1,
  "jam": 4,
  "jam_clock_ms": 89000,
  "period_clock_ms": 412000,
  "jam_running": true,
  "in_jam": true,
  "game_state": "Running",
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

### `GET /raw`
Full flat state dict as received from the scoreboard WebSocket. Useful for discovering all available fields or debugging.

### `GET /health`
Connection status:
```json
{"connected": true, "scoreboard_version": "v5.0.0"}
```

### `GET /docs`
Auto-generated interactive OpenAPI docs (Swagger UI).

## Running tests

```bash
pytest
```

Tests use a mock WebSocket server — no real scoreboard needed.

## How it works

1. On startup, a background asyncio task connects to `ws://<scoreboard-host>:<scoreboard-port>/WS/`
2. Subscribes to `ScoreBoard.CurrentGame` to receive all live game state
3. Maintains an in-memory state dict, applying incremental patches as the scoreboard broadcasts them
4. `GET /live` reads from that dict and maps the raw CRG key names to clean JSON fields
5. Auto-reconnects if the WebSocket drops

## CRG WebSocket protocol

The proxy uses the CRG scoreboard's native WebSocket API:

- **Endpoint:** `ws://host:8000/WS/`
- **Subscribe:** `{"action": "Register", "paths": ["ScoreBoard.CurrentGame"]}`
- **Updates:** `{"state": {"ScoreBoard.CurrentGame.Clock(Jam).Time": 89000, ...}}`
- A `null` value means that key was deleted/reset
- Full protocol docs available at `http://scoreboard-host:8000/documentation/wiki-snapshot.html`
- Live key browser at `http://scoreboard-host:8000/json/state.html`

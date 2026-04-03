# Extending the Derby Scoreboard API

This guide covers the most common extension tasks. The codebase is intentionally
small (3 source files) so changes are low-risk and easy to reason about.

---

## Architecture overview

```
main.py      FastAPI app, endpoint definitions, startup/shutdown lifecycle
client.py    Async WebSocket client, in-memory state dict, field mapping
models.py    Pydantic response models (defines the JSON shape of each endpoint)
```

The WS client runs as a background asyncio task inside the same process as the
API. No database, no queue, no external dependencies beyond the scoreboard.

---

## Adding a new field to `/live`

The field mapping is fully declarative. You never need to touch the mapping
logic — just add a row to a dict and a field to the model.

**Step 1 — Add the field to the Pydantic model (`models.py`)**

```python
class TeamState(BaseModel):
    ...
    no_initial: Optional[bool] = None   # ← add here
```

Or for a top-level game field:

```python
class LiveState(BaseModel):
    ...
    in_overtime: Optional[bool] = None  # ← add here
```

**Step 2 — Add the CRG key mapping (`client.py`)**

For a per-team field, add to `TEAM_FIELD_MAP`:

```python
TEAM_FIELD_MAP: Dict[str, tuple[str, type]] = {
    ...
    "no_initial": ("NoInitial", bool),   # ← add here
}
```

The key is the `TeamState` field name. The value is a tuple of
`(suffix, Python type)` where the suffix is relative to the `Team(N).` prefix.

For a top-level game field, add to `GAME_FIELD_MAP`:

```python
GAME_FIELD_MAP: Dict[str, tuple[str, type]] = {
    ...
    "in_overtime": ("InOvertime", bool),  # ← add here
}
```

That's it. The field will appear in `/live` responses on the next request.
No other code changes needed.

---

## Timeout fields

When no timeout is active every timeout field is `null`.  When a timeout or
official review is running the following fields are populated:

| Field | Type | Description |
|---|---|---|
| `timeout_type` | `string \| null` | One of `team_timeout`, `official_timeout`, `official_review`, or `timeout`. Resets to `null` when `jam_running` is true. |
| `timeout_clock_ms` | `int \| null` | Raw millisecond value from CRG `Clock(Timeout)`. |
| `timeout_clock` | `string \| null` | M:SS formatted string (e.g. `"1:30"`). Null when no timeout active. |

`timeout_type` is derived by the client from the CRG `TimeoutOwner` and
`OfficialReview` fields.  The normalization table is in `client.py`
(`TIMEOUT_TYPE_MAP`).

---

## Lead jammer and jam status

These fields are part of `TeamState` and `LiveState` respectively:

| Field | Model | Type | Description |
|---|---|---|---|
| `lead` | `TeamState` | `bool \| null` | True when this team's jammer has lead jammer status as reported by CRG. |
| `display_lead` | `TeamState` | `bool \| null` | CRG's display-facing lead flag — mirrors `lead` except it can persist briefly after calloff for scoreboard display purposes. |
| `calloff` | `TeamState` | `bool \| null` | True when the jammer called off the jam. |
| `lost` | `TeamState` | `bool \| null` | True when lead jammer status has been lost (e.g. penalty). |
| `jam_running` | `LiveState` | `bool \| null` | True while the jam clock is actively counting down. |
| `in_jam` | `LiveState` | `bool \| null` | True from the moment a jam starts until the jam is officially ended by the NSO. Use this (not `jam_running`) to detect whether a jam is "live". |

Typical overlay logic:

```javascript
// Show the star when a team has lead
teamEl.classList.toggle("lead", state.team1.lead === true);

// Detect a jam that has finished its clock but not been stopped yet
const jamExpired = state.in_jam && !state.jam_running;
```

---

## Star pass

`star_pass` is a `bool | null` field on `TeamState`.  When `true` the jammer
and pivot slots are **swapped** by the client before the response is built, so
consumers always find the active jammer in `jammer` and the active pivot in
`pivot` regardless of who originally wore the star.

```
Before star pass:   jammer = original jammer,  pivot = original pivot
After star pass:    jammer = original pivot,    pivot = original jammer
```

The `star_pass` flag itself is still exposed so overlays can show a star-pass
indicator or suppress the pivot label.

**Display example:**

```javascript
if (team.star_pass) {
  jammerEl.textContent = `${team.jammer.number} (SP)`;
  pivotEl.textContent  = team.pivot.number;   // original jammer, now a blocker
}
```

---

## Adding a new endpoint

Add a route inside `create_app()` in `main.py`, following the existing pattern:

```python
@app.get(
    "/timeout",
    responses={503: {"description": "Scoreboard not connected"}},
    summary="Current timeout info",
)
async def get_timeout(request: Request) -> dict:
    sb = request.app.state.scoreboard_client
    if not sb.connected:
        raise HTTPException(
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
            detail="scoreboard not connected",
            headers={"Retry-After": "2"},
        )
    state = sb.get_raw_state()
    return {
        "timeout_owner": state.get("ScoreBoard.CurrentGame.TimeoutOwner"),
        "official_review": state.get("ScoreBoard.CurrentGame.OfficialReview"),
    }
```

Always guard with `if not sb.connected` and raise `HTTPException(503)` so the
endpoint returns a clean, spec-documented error with a `Retry-After` header
rather than silent nulls when the scoreboard is down.

You can discover available key names by hitting `GET /raw` while the scoreboard
is running, or browsing `http://localhost:8000/json/state.html`.

---

## Subscribing to additional scoreboard namespaces

By default the proxy only subscribes to `ScoreBoard.CurrentGame`. If you need
data from other namespaces (e.g. settings, officials roster), add them to
`REGISTER_MSG` in `client.py`:

```python
REGISTER_MSG = json.dumps({
    "action": "Register",
    "paths": [
        "ScoreBoard.CurrentGame",
        "ScoreBoard.Version(release)",
        "ScoreBoard.Rulesets",        # ← add here
    ],
})
```

Those keys will then appear in `/raw` and be available for mapping.

---

## Resilience notes

- The WS client loop **never exits** except on clean shutdown (`CancelledError`).
  Any network error or unexpected exception is logged and the client retries
  after `RECONNECT_DELAY` seconds (default: 2).
- `/live` returns HTTP 503 when disconnected. Pollers should check for this and
  hold their last-known state rather than displaying zeros.
- `/health` always returns, even when disconnected. Recommended as a watchdog.
- The proxy can start before the scoreboard — it will just log retry attempts
  until the scoreboard comes up.

---

## Known limitations

| Limitation | Notes |
|---|---|
| In-memory state only | If the proxy restarts, state is empty until the scoreboard sends the next update (usually within 1–2 seconds of connection). |
| Single scoreboard | The proxy is designed for one scoreboard. Running two proxies pointing at different scoreboards is fine; running one proxy for two scoreboards is not supported. |
| Read-only | The proxy exposes no write endpoints. To send commands to the scoreboard, use the scoreboard's own UI or its WebSocket `Set` action directly. |
| No auth | Intentional — this is a local LAN tool. Do not expose port 5001 to the public internet. |
| CRG v5+ keys only | Key names were verified against CRG v2025.x. If running an older v4 scoreboard, some keys will be absent (particularly `CurrentGame.*` prefix). Check `/raw` to see what the scoreboard actually sends. |

---

## Running during an event

The simplest approach — and fine for event use — is to open a terminal and run:

```powershell
python main.py
```

Leave the terminal open for the duration of the event. The proxy will log
reconnect attempts if the scoreboard restarts, and resume automatically.

---

## Future improvement: running as a Windows service

If the machine reboots frequently or runs unattended, NSSM (Non-Sucking
Service Manager) can register the proxy as a Windows service that starts on
boot and restarts on crash. Not needed for typical event use.

> **Low-RAM machines:** If you do set this up, avoid Docker Desktop — it
> requires WSL2, which reserves 1–2 GB of RAM before a container even starts.
> The proxy uses ~60 MB as a native process.

```powershell
# Find your Python executable path first:
where python
# Example: C:\Users\YourName\AppData\Local\Programs\Python\Python313\python.exe

choco install nssm -y
nssm install DerbyScoreboardAPI "C:\Users\YourName\AppData\Local\Programs\Python\Python313\python.exe" "C:\path\to\derby-scoreboard-api\main.py"
nssm start DerbyScoreboardAPI
```

> **Important:** Always use the **full path** to `python.exe`. Windows services
> do not inherit user PATH entries, so `python` alone will fail to resolve.

Alternatively, Task Scheduler with "Start at logon" and "Run whether user is
logged on or not" achieves the same without installing NSSM.

---

## GitHub Actions CI

Add the file below to the repo so every push and PR automatically runs the
full test suite in the cloud. No secrets or external services are needed —
the tests use an in-process mock WebSocket server.

**Create `.github/workflows/test.yml`:**

```yaml
name: Tests

on:
  push:
    branches: ["main"]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run tests
        run: python -m pytest tests/ -v
```

**What this gives you:**
- Every push to `main` runs all 33 tests in < 30 seconds.
- PRs block on red CI — you'll know immediately if a change breaks something.
- The matrix can be extended to test multiple Python versions by changing
  `python-version` to a list: `["3.11", "3.12", "3.13"]`.

**To add the file locally and push:**

```bash
mkdir -p .github/workflows
# create the file above, then:
git add .github/workflows/test.yml
git commit -m "ci: add GitHub Actions test workflow"
git push
```

After the first push, the "Actions" tab on the GitHub repo page will show a
green checkmark (or red ✗ if a test fails).


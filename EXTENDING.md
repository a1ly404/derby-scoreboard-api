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
TEAM_FIELD_MAP: Dict[str, tuple] = {
    ...
    "no_initial": ("NoInitial", bool),   # ← add here
}
```

The key is the `TeamState` field name. The value is a tuple of
`(suffix, Python type)` where the suffix is relative to the `Team(N).` prefix.

For a top-level game field, add to `GAME_FIELD_MAP`:

```python
GAME_FIELD_MAP: Dict[str, tuple] = {
    ...
    "in_overtime": ("InOvertime", bool),  # ← add here
}
```

That's it. The field will appear in `/live` responses on the next request.
No other code changes needed.

---

## Adding a new endpoint

Add a route inside `create_app()` in `main.py`, following the existing pattern:

```python
@app.get("/timeout", summary="Current timeout info")
async def get_timeout(request: Request) -> dict:
    sb = request.app.state.scoreboard_client
    if not sb.connected:
        return JSONResponse(
            {"detail": "scoreboard not connected"},
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
        )
    state = sb.get_raw_state()
    return {
        "timeout_owner": state.get("ScoreBoard.CurrentGame.TimeoutOwner"),
        "official_review": state.get("ScoreBoard.CurrentGame.OfficialReview"),
    }
```

Always guard with `if not sb.connected` so the endpoint returns a clean 503
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

## Running in the background as a Windows service (optional)

If you want the proxy to start automatically with Windows, use NSSM
(Non-Sucking Service Manager):

```powershell
choco install nssm -y
nssm install DerbyScoreboardAPI python "C:\path\to\derby-scoreboard-api\main.py"
nssm start DerbyScoreboardAPI
```

Or use Task Scheduler with "Start at logon" and "Run whether user is logged on or not".

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


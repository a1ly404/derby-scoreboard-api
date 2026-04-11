# CLAUDE.md

This file provides guidance to Claude Code when working in the `derby-scoreboard-api` project.

## Project overview

Lightweight Python/FastAPI REST proxy that connects to a CRG ScoreBoard WebSocket and re-exposes the game state as clean HTTP endpoints (`GET /live`, `GET /raw`, `GET /health`).

## Key files

| File | Purpose |
|---|---|
| `main.py` | FastAPI app, CLI args, endpoint handlers |
| `client.py` | Async WebSocket client to CRG scoreboard |
| `models.py` | **Pydantic models — the API contract source of truth** |
| `proxy.py` | Blue/green reverse proxy for zero-downtime deploys |
| `requirements.txt` | Python dependencies |

## Running

```sh
python main.py                          # default: connects to ws://localhost:8000, serves on :5001
python main.py --scoreboard-port 8002   # CRG on a different port
```

## Testing

```sh
pytest
```

## API contract rules

### `models.py` is the single source of truth

Every downstream consumer (TypeScript, display overlays, bridge services) generates its types from the OpenAPI spec that FastAPI produces from `models.py`.

**When you change `models.py`:**

1. **Never remove or rename a field** without confirming no downstream consumer uses it. Known consumers:
   - `derby-stat-tracker/apps/live-tracker` — imports `LiveState`, `TeamState`, `SkaterPosition`, `HealthState`
   - `derby-scoreboard-display` — polls `GET /live` for overlay rendering
   - `derby-stat-tracker/services/live-bridge` — polls `GET /live` for Supabase persistence
2. **Adding a field is safe** — new optional fields with defaults won't break consumers.
3. **After any model change**, remind the user to regenerate the TypeScript types in `derby-stat-tracker`:
   ```sh
   cd ../derby-stat-tracker && npm run sync:api-types
   ```
4. **Never hand-edit** `derby-stat-tracker/apps/live-tracker/src/types/scoreboard-api.ts` — it is auto-generated from this project's OpenAPI spec.

### Field conventions

- Use `snake_case` for all field names (Pydantic serializes as-is).
- Fields that may be absent when the scoreboard is disconnected must be `Optional[T] = None`.
- Clock values are in **milliseconds** (suffix `_ms`). Human-readable clocks are parallel `str` fields (e.g. `jam_clock_ms` + `jam_clock`).
- Boolean flags use present tense: `in_jam`, `in_box`, `jam_running`, `in_lineup`.

## Overlay URL format

When referencing the custom overlay served by CRG, the correct URL path is:

```
/custom/view/eod-custom-overlay/index.html?home=%23HEX&away=%23HEX
```

The overlay lives in CRG's `html/custom/view/` directory, **not** `html/custom/` directly.
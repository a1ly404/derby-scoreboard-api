from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from models import LiveState, TeamState

logger = logging.getLogger(__name__)

REGISTER_MSG = json.dumps({
    "action": "Register",
    "paths": [
        "ScoreBoard.CurrentGame",
        "ScoreBoard.Version(release)",
    ],
})

PING_MSG = json.dumps({"action": "Ping"})

RECONNECT_DELAY = 2  # seconds
PING_INTERVAL = 30   # seconds

_PREFIX = "ScoreBoard.CurrentGame."
_VERSION_KEY = "ScoreBoard.Version(release)"

# ---------------------------------------------------------------------------
# Declarative field maps — add a new field in 2 steps:
#   1. Add a field to the relevant Pydantic model in models.py
#   2. Add an entry here: "model_field_name": ("CRG.Key.Suffix", python_type)
# ---------------------------------------------------------------------------

# Fields that appear once per team.  The Team(N). prefix is added automatically.
TEAM_FIELD_MAP: Dict[str, tuple] = {
    "name":           ("Name",                         str),
    "score":          ("Score",                        int),
    "jam_score":      ("JamScore",                     int),
    "jammer":         ("Position(Jammer).Name",        str),
    "jammer_number":  ("Position(Jammer).RosterNumber",str),
    "lead":           ("Lead",                         bool),
    "display_lead":   ("DisplayLead",                  bool),
    "calloff":        ("Calloff",                      bool),
    "lost":           ("Lost",                         bool),
    "star_pass":      ("StarPass",                     bool),
}

# Top-level game fields.  Suffixes are relative to ScoreBoard.CurrentGame.
GAME_FIELD_MAP: Dict[str, tuple] = {
    "period":          ("Clock(Period).Number", int),
    "jam":             ("Clock(Jam).Number",    int),
    "jam_clock_ms":    ("Clock(Jam).Time",      int),
    "period_clock_ms": ("Clock(Period).Time",   int),
    "jam_running":     ("Clock(Jam).Running",   bool),
    "in_jam":          ("InJam",                bool),
    "game_state":      ("State",                str),
}


def _coerce(value: Any, target_type: type) -> Any:
    """Safely coerce a WS value to the expected Python type."""
    if value is None:
        return None
    try:
        return target_type(value)
    except (ValueError, TypeError):
        return value


class ScoreboardClient:
    """
    Async WebSocket client for the CRG scoreboard.

    Connects to ws://<host>:<port>/WS/, subscribes to the full
    ScoreBoard.CurrentGame namespace, and maintains a live state dict
    that is updated in real time as the scoreboard pushes changes.

    Null values from the server indicate key deletion; this client
    removes those keys from the local state dict.

    Auto-reconnects on disconnect with a short delay.
    """

    def __init__(self, host: str = "localhost", port: int = 8000) -> None:
        self.host = host
        self.port = port
        self._state: Dict[str, Any] = {}
        self._connected = False
        self._task: Optional[asyncio.Task] = None

    @property
    def connected(self) -> bool:
        return self._connected

    def get_raw_state(self) -> Dict[str, Any]:
        """Return a copy of the raw flat state dict."""
        return dict(self._state)

    def get_version(self) -> Optional[str]:
        return self._state.get(_VERSION_KEY)

    def _apply_update(self, state_patch: Dict[str, Any]) -> None:
        """Merge a state patch into local state. None values delete keys."""
        for key, value in state_patch.items():
            if value is None:
                self._state.pop(key, None)
            else:
                self._state[key] = value

    def _get(self, suffix: str, target_type: type = str) -> Any:
        """Get a CurrentGame key by its suffix (part after the prefix)."""
        raw = self._state.get(_PREFIX + suffix)
        if raw is None:
            return None
        return _coerce(raw, target_type)

    def _team(self, n: int) -> TeamState:
        """Build a TeamState for team n using TEAM_FIELD_MAP."""
        prefix = f"Team({n})."
        return TeamState(**{
            field: self._get(prefix + suffix, typ)
            for field, (suffix, typ) in TEAM_FIELD_MAP.items()
        })

    def get_live_state(self) -> LiveState:
        """Build and return a LiveState model from current raw state."""
        game_fields = {
            field: self._get(suffix, typ)
            for field, (suffix, typ) in GAME_FIELD_MAP.items()
        }
        return LiveState(
            **game_fields,
            team1=self._team(1),
            team2=self._team(2),
        )

    async def _run_once(self, uri: str) -> None:
        """Connect, subscribe, and receive updates until disconnect."""
        logger.info("Connecting to %s", uri)
        async with websockets.connect(uri, ping_interval=None) as ws:
            self._connected = True
            logger.info("Connected to scoreboard WS")
            await ws.send(REGISTER_MSG)

            ping_task = asyncio.create_task(self._ping_loop(ws))
            try:
                async for raw_msg in ws:
                    try:
                        msg = json.loads(raw_msg)
                    except json.JSONDecodeError:
                        logger.warning("Non-JSON message received: %r", raw_msg)
                        continue

                    if "state" in msg:
                        self._apply_update(msg["state"])
                    elif "error" in msg:
                        logger.warning("Scoreboard error: %s", msg["error"])
            except ConnectionClosed:
                pass
            finally:
                ping_task.cancel()
                try:
                    await ping_task
                except asyncio.CancelledError:
                    pass

    async def _ping_loop(self, ws) -> None:
        """Send periodic pings to keep the connection alive."""
        while True:
            await asyncio.sleep(PING_INTERVAL)
            try:
                await ws.send(PING_MSG)
            except ConnectionClosed:
                break

    async def run(self) -> None:
        """
        Main loop: connect and auto-reconnect on failure.
        This loop is intentionally infinite and swallows all exceptions so
        that a scoreboard restart, network blip, or any other error never
        crashes the proxy process — it just reconnects after RECONNECT_DELAY.
        """
        uri = f"ws://{self.host}:{self.port}/WS/"
        while True:
            self._connected = False
            try:
                await self._run_once(uri)
            except asyncio.CancelledError:
                # Proxy is shutting down — let the cancellation propagate.
                raise
            except OSError as exc:
                logger.warning("Scoreboard unreachable (%s) — retrying in %ds", exc, RECONNECT_DELAY)
            except Exception:
                logger.exception("Unexpected WS client error — retrying in %ds", RECONNECT_DELAY)
            finally:
                self._connected = False
            await asyncio.sleep(RECONNECT_DELAY)

    def start(self) -> asyncio.Task:
        """Schedule the run loop as an asyncio background task."""
        self._task = asyncio.create_task(self.run())
        return self._task

    def stop(self) -> None:
        """Cancel the background task."""
        if self._task is not None:
            self._task.cancel()

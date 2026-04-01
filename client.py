from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from models import LiveState, SkaterPosition, TeamState

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
TEAM_FIELD_MAP: Dict[str, tuple[str, type]] = {
    "name": ("Name", str),
    "score": ("Score", int),
    "jam_score": ("JamScore", int),
    "lead": ("Lead", bool),
    "display_lead": ("DisplayLead", bool),
    "calloff": ("Calloff", bool),
    "lost": ("Lost", bool),
    "star_pass": ("StarPass", bool),
}

# On-track positions.  Name maps to the CRG Position() key; dict key maps to TeamState field.
POSITION_MAP: Dict[str, str] = {
    "jammer": "Jammer",
    "pivot": "Pivot",
    "blocker1": "Blocker1",
    "blocker2": "Blocker2",
    "blocker3": "Blocker3",
}

# Top-level game fields.  Suffixes are relative to ScoreBoard.CurrentGame.
GAME_FIELD_MAP: Dict[str, tuple[str, type]] = {
    "period": ("Clock(Period).Number", int),
    "jam": ("Clock(Jam).Number", int),
    "jam_clock_ms": ("Clock(Jam).Time", int),
    "period_clock_ms": ("Clock(Period).Time", int),
    "jam_running": ("Clock(Jam).Running", bool),
    "in_jam": ("InJam", bool),
    "game_state": ("State", str),
}


def _coerce(value: Any, target_type: type) -> Any:
    """Safely coerce a WS value to the expected Python type.

    Special-cases bool so that the string "false" (which Python normally
    coerces to True as a non-empty string) correctly returns False.
    The CRG scoreboard sends native JSON booleans, but this guards against
    proxies or older versions that may stringify them.
    """
    if value is None:
        return None
    if target_type is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() not in ("false", "0", "no", "")
        return bool(value)
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
        self._last_update: Optional[float] = None
        self._task: Optional[asyncio.Task] = None
        self._box_elapsed: Dict[str, int] = {}  # key: "<team_n>.<crg_pos>"
        self._prev_jam_clock_ms: Optional[int] = None
        self._prev_jam_running: Optional[bool] = None

    @property
    def connected(self) -> bool:
        return self._connected

    def get_raw_state(self) -> Dict[str, Any]:
        """Return a copy of the raw flat state dict."""
        return dict(self._state)

    def get_seconds_since_update(self) -> Optional[float]:
        """Seconds since the last state update from the scoreboard.

        Returns None if no update has ever been received (e.g. just connected
        or never connected). Useful for detecting a frozen scoreboard that is
        technically connected but not sending updates.
        """
        if self._last_update is None:
            return None
        return round(time.monotonic() - self._last_update, 1)

    def get_version(self) -> Optional[str]:
        return self._state.get(_VERSION_KEY)

    def _apply_update(self, state_patch: Dict[str, Any]) -> None:
        """Merge a state patch into local state. None values delete keys."""
        if not isinstance(state_patch, dict):
            raise TypeError(f"Expected dict state patch, got {type(state_patch).__name__}")
        for key, value in state_patch.items():
            if value is None:
                self._state.pop(key, None)
            else:
                self._state[key] = value
        self._last_update = time.monotonic()

    def _get(self, suffix: str, target_type: type = str) -> Any:
        """Get a CurrentGame key by its suffix (part after the prefix)."""
        raw = self._state.get(_PREFIX + suffix)
        if raw is None:
            return None
        return _coerce(raw, target_type)

    def _tick_box_timers(self) -> None:
        """Accumulate jam-clock elapsed time for each in-box skater.

        Called after every state update.  Only adds time when jam_running is
        True and the jam clock has ticked down (positive delta).  Automatically
        resets a skater's elapsed counter when they leave the box.
        """
        jam_clock = self._get("Clock(Jam).Time", int)
        jam_running = self._get("Clock(Jam).Running", bool)

        # Maintain per-position elapsed counters — reset on box exit.
        for team_n in (1, 2):
            for crg_pos in POSITION_MAP.values():
                key = f"{team_n}.{crg_pos}"
                in_box = (
                    self._get(f"Team({team_n}).Position({crg_pos}).PenaltyBox", bool)
                    or False
                )
                if not in_box:
                    self._box_elapsed.pop(key, None)
                elif key not in self._box_elapsed:
                    # Skater just entered — initialise at zero
                    self._box_elapsed[key] = 0

        # Accumulate only when the jam was *already* running at the previous tick.
        # Requiring _prev_jam_running=True prevents a large spurious delta from
        # being counted when jam_running flips True in the same message as a
        # clock jump (e.g. clock resets to 120 s at the start of a new jam).
        if (
            jam_running
            and self._prev_jam_running
            and self._prev_jam_clock_ms is not None
            and jam_clock is not None
        ):
            delta = self._prev_jam_clock_ms - jam_clock
            if delta > 0:  # negative means clock was reset; skip
                for key in list(self._box_elapsed.keys()):
                    self._box_elapsed[key] += delta

        self._prev_jam_clock_ms = jam_clock
        self._prev_jam_running = jam_running

    def _team(self, n: int) -> TeamState:
        """Build a TeamState for team n using TEAM_FIELD_MAP and POSITION_MAP."""
        prefix = f"Team({n})."
        flat_fields = {
            field: self._get(prefix + suffix, typ)
            for field, (suffix, typ) in TEAM_FIELD_MAP.items()
        }
        positions = {
            field: SkaterPosition(
                name=self._get(f"{prefix}Position({crg_pos}).Name"),
                number=self._get(f"{prefix}Position({crg_pos}).RosterNumber"),
                in_box=self._get(f"{prefix}Position({crg_pos}).PenaltyBox", bool) or False,
                box_elapsed_jam_ms=self._box_elapsed.get(f"{n}.{crg_pos}"),
            )
            for field, crg_pos in POSITION_MAP.items()
        }
        return TeamState(**flat_fields, **positions)

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

                    # Isolate per-message processing so a single bad message
                    # never kills the entire WS receive loop.
                    try:
                        if "state" in msg:
                            self._apply_update(msg["state"])
                            self._tick_box_timers()
                        elif "error" in msg:
                            logger.warning("Scoreboard error: %s", msg["error"])
                    except Exception:
                        logger.exception("Error processing scoreboard message, skipping: %r", msg)
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

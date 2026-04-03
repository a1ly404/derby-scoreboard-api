from __future__ import annotations

import asyncio
import json
import logging
import math
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

RECONNECT_DELAY = 2          # seconds
PING_INTERVAL = 30           # seconds
PENALTY_BOX_DURATION_S = 30  # seconds

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
    "timeout_clock_ms": ("Clock(Timeout).Time", int),
}


def _ms_to_clock(ms: Optional[int]) -> Optional[str]:
    """Convert milliseconds to a M:SS display string. Returns None for None input."""
    if ms is None:
        return None
    total_s = max(0, ms) // 1000
    return f"{total_s // 60}:{total_s % 60:02d}"


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
        self._box_entry_times: Dict[str, int] = {}   # key: "<team_n>.<crg_pos>" -> epoch ms
        self._box_entry_mono: Dict[str, float] = {}   # key: "<team_n>.<crg_pos>" -> monotonic s
        self._was_in_box: Dict[str, bool] = {}        # key: "<team_n>.<crg_pos>" -> last known in_box

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

    def _update_box_entry_times(self) -> None:
        """Record entry time on observed false→True penalty-box transitions.

        Called after every state update. Entry times are only set when a
        false→True transition is observed; skaters already in the box when
        the client first connects keep None until an exit+re-entry occurs.
        The monotonic clock is stored for stable countdown computation;
        epoch ms is also stored for client overlay usage.
        """
        for team_n in (1, 2):
            for crg_pos in POSITION_MAP.values():
                key = f"{team_n}.{crg_pos}"
                in_box = (
                    self._get(f"Team({team_n}).Position({crg_pos}).PenaltyBox", bool)
                    or False
                )
                was_in_box = self._was_in_box.get(key, False)
                if in_box and not was_in_box:
                    self._box_entry_times[key] = int(time.time() * 1000)
                    self._box_entry_mono[key] = time.monotonic()
                elif not in_box:
                    self._box_entry_times.pop(key, None)
                    self._box_entry_mono.pop(key, None)
                self._was_in_box[key] = in_box

    def _team(self, n: int) -> TeamState:
        """Build a TeamState for team n using TEAM_FIELD_MAP and POSITION_MAP."""
        prefix = f"Team({n})."
        flat_fields = {
            field: self._get(prefix + suffix, typ)
            for field, (suffix, typ) in TEAM_FIELD_MAP.items()
        }
        positions = {}
        for field, crg_pos in POSITION_MAP.items():
            entered_ms = self._box_entry_times.get(f"{n}.{crg_pos}")
            entered_mono = self._box_entry_mono.get(f"{n}.{crg_pos}")
            if entered_mono is not None:
                elapsed_s = time.monotonic() - entered_mono
                remaining: Optional[int] = max(0, math.ceil(PENALTY_BOX_DURATION_S - elapsed_s))
            else:
                remaining = None
            positions[field] = SkaterPosition(
                name=self._get(f"{prefix}Position({crg_pos}).Name"),
                number=self._get(f"{prefix}Position({crg_pos}).RosterNumber"),
                in_box=self._get(f"{prefix}Position({crg_pos}).PenaltyBox", bool) or False,
                box_entered_at_ms=entered_ms,
                box_time_remaining_s=remaining,
            )
        # When a star pass is successful the pivot receives the jammer cover and
        # becomes the new jammer.  Swap the two positions so downstream consumers
        # always read the current jammer from the `jammer` field.
        if flat_fields.get("star_pass"):
            positions["jammer"], positions["pivot"] = positions["pivot"], positions["jammer"]
        return TeamState(**flat_fields, **positions)

    @staticmethod
    def _normalize_timeout_type(
        game_state: Optional[str],
        jam_running: Optional[bool],
        clock_timeout_running: Optional[bool] = None,
    ) -> Optional[str]:
        """Normalize timeout/review from game state and timeout clock.

        Uses Clock(Timeout).Running as the authoritative indicator that a
        timeout is active — this fires even when CRG's State field hasn't
        updated yet or only reads "Timeout" without a type qualifier.
        game_state is then used solely to refine the type label.
        Returns None when a jam is running (timeout is over).
        """
        if jam_running:
            return None

        in_timeout = bool(clock_timeout_running)
        state = (game_state or "").strip().lower()

        if "official review" in state:
            return "official_review"
        if "official timeout" in state:
            return "official_timeout"
        if "team timeout" in state:
            return "team_timeout"
        if "timeout" in state or in_timeout:
            return "timeout"
        if "review" in state:
            return "official_review"
        return None

    def get_live_state(self) -> LiveState:
        """Build and return a LiveState model from current raw state."""
        game_fields = {
            field: self._get(suffix, typ)
            for field, (suffix, typ) in GAME_FIELD_MAP.items()
        }
        clock_timeout_running = self._get("Clock(Timeout).Running", bool)
        # Check if intermission clock is running — if so, override game_state to show intermission
        intermission_clock_running = self._get("Clock(Intermission).Running", bool)
        if intermission_clock_running:
            game_fields["game_state"] = "Intermission"
        # Pop timeout_clock_ms so we can conditionally suppress it below
        # without it conflicting with the **game_fields unpack.
        raw_timeout_clock_ms = game_fields.pop("timeout_clock_ms", None)
        timeout_type = self._normalize_timeout_type(
            game_state=game_fields.get("game_state"),
            jam_running=game_fields.get("jam_running"),
            clock_timeout_running=clock_timeout_running,
        )
        timeout_clock_ms = raw_timeout_clock_ms if timeout_type else None
        return LiveState(
            **game_fields,
            jam_clock=_ms_to_clock(game_fields.get("jam_clock_ms")),
            period_clock=_ms_to_clock(game_fields.get("period_clock_ms")),
            timeout_type=timeout_type,
            # Suppress clock value when no timeout is active — CRG may retain
            # the last timeout time even between jams.
            timeout_clock_ms=timeout_clock_ms,
            timeout_clock=_ms_to_clock(timeout_clock_ms),
            team1=self._team(1),
            team2=self._team(2),
        )

    async def _run_once(self, uri: str) -> None:
        """Connect, subscribe, and receive updates until disconnect."""
        logger.info("Connecting to %s", uri)
        async with websockets.connect(uri, ping_interval=None) as ws:
            self._box_entry_times.clear()
            self._box_entry_mono.clear()
            self._was_in_box.clear()
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
                            self._update_box_entry_times()
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

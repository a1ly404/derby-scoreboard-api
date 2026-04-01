from __future__ import annotations

import asyncio
import json
import socket
from typing import Any, Dict, List, Optional

import pytest
import pytest_asyncio
import websockets


INITIAL_STATE: Dict[str, Any] = {
    "ScoreBoard.Version(release)": "v5.0.0-test",
    "ScoreBoard.CurrentGame.State": "Running",
    "ScoreBoard.CurrentGame.InJam": False,
    "ScoreBoard.CurrentGame.InPeriod": True,
    "ScoreBoard.CurrentGame.Clock(Jam).Time": 60000,
    "ScoreBoard.CurrentGame.Clock(Jam).Running": False,
    "ScoreBoard.CurrentGame.Clock(Jam).Number": 3,
    "ScoreBoard.CurrentGame.Clock(Period).Time": 900000,
    "ScoreBoard.CurrentGame.Clock(Period).Running": True,
    "ScoreBoard.CurrentGame.Clock(Period).Number": 1,
    "ScoreBoard.CurrentGame.Team(1).Name": "Home Team",
    "ScoreBoard.CurrentGame.Team(1).FullName": "The Home Team",
    "ScoreBoard.CurrentGame.Team(1).Score": 42,
    "ScoreBoard.CurrentGame.Team(1).JamScore": 0,
    "ScoreBoard.CurrentGame.Team(1).Lead": False,
    "ScoreBoard.CurrentGame.Team(1).DisplayLead": False,
    "ScoreBoard.CurrentGame.Team(1).Calloff": False,
    "ScoreBoard.CurrentGame.Team(1).Lost": False,
    "ScoreBoard.CurrentGame.Team(1).StarPass": False,
    "ScoreBoard.CurrentGame.Team(1).Position(Jammer).Name": "Speed Demon",
    "ScoreBoard.CurrentGame.Team(1).Position(Jammer).RosterNumber": "88",
    "ScoreBoard.CurrentGame.Team(1).Position(Jammer).PenaltyBox": False,
    "ScoreBoard.CurrentGame.Team(1).Position(Pivot).Name": "Iron Curtain",
    "ScoreBoard.CurrentGame.Team(1).Position(Pivot).RosterNumber": "22",
    "ScoreBoard.CurrentGame.Team(1).Position(Pivot).PenaltyBox": False,
    "ScoreBoard.CurrentGame.Team(1).Position(Blocker1).Name": "Brick Wall",
    "ScoreBoard.CurrentGame.Team(1).Position(Blocker1).RosterNumber": "11",
    "ScoreBoard.CurrentGame.Team(1).Position(Blocker1).PenaltyBox": False,
    "ScoreBoard.CurrentGame.Team(1).Position(Blocker2).Name": "Crash Test",
    "ScoreBoard.CurrentGame.Team(1).Position(Blocker2).RosterNumber": "33",
    "ScoreBoard.CurrentGame.Team(1).Position(Blocker2).PenaltyBox": False,
    "ScoreBoard.CurrentGame.Team(1).Position(Blocker3).Name": "Ricochet",
    "ScoreBoard.CurrentGame.Team(1).Position(Blocker3).RosterNumber": "44",
    "ScoreBoard.CurrentGame.Team(1).Position(Blocker3).PenaltyBox": False,
    "ScoreBoard.CurrentGame.Team(2).Name": "Away Team",
    "ScoreBoard.CurrentGame.Team(2).FullName": "The Away Team",
    "ScoreBoard.CurrentGame.Team(2).Score": 37,
    "ScoreBoard.CurrentGame.Team(2).JamScore": 0,
    "ScoreBoard.CurrentGame.Team(2).Lead": False,
    "ScoreBoard.CurrentGame.Team(2).DisplayLead": False,
    "ScoreBoard.CurrentGame.Team(2).Calloff": False,
    "ScoreBoard.CurrentGame.Team(2).Lost": False,
    "ScoreBoard.CurrentGame.Team(2).StarPass": False,
    "ScoreBoard.CurrentGame.Team(2).Position(Jammer).Name": "Lightning Bolt",
    "ScoreBoard.CurrentGame.Team(2).Position(Jammer).RosterNumber": "7",
    "ScoreBoard.CurrentGame.Team(2).Position(Jammer).PenaltyBox": False,
    "ScoreBoard.CurrentGame.Team(2).Position(Pivot).Name": "Storm Front",
    "ScoreBoard.CurrentGame.Team(2).Position(Pivot).RosterNumber": "55",
    "ScoreBoard.CurrentGame.Team(2).Position(Pivot).PenaltyBox": False,
    "ScoreBoard.CurrentGame.Team(2).Position(Blocker1).Name": "Ground Zero",
    "ScoreBoard.CurrentGame.Team(2).Position(Blocker1).RosterNumber": "66",
    "ScoreBoard.CurrentGame.Team(2).Position(Blocker1).PenaltyBox": False,
    "ScoreBoard.CurrentGame.Team(2).Position(Blocker2).Name": "Shockwave",
    "ScoreBoard.CurrentGame.Team(2).Position(Blocker2).RosterNumber": "77",
    "ScoreBoard.CurrentGame.Team(2).Position(Blocker2).PenaltyBox": False,
    "ScoreBoard.CurrentGame.Team(2).Position(Blocker3).Name": "Afterburn",
    "ScoreBoard.CurrentGame.Team(2).Position(Blocker3).RosterNumber": "99",
    "ScoreBoard.CurrentGame.Team(2).Position(Blocker3).PenaltyBox": False,
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class MockScoreboardServer:
    """
    A minimal mock of the CRG scoreboard WebSocket server.

    Handles Register messages by sending the full INITIAL_STATE snapshot.
    Supports push_update() to send incremental state patches to all
    connected clients (mirrors how the real scoreboard streams deltas).
    """

    def __init__(self) -> None:
        self.port: int = _free_port()
        self._connections: List = []
        self._server = None

    async def _handler(self, ws) -> None:
        self._connections.append(ws)
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("action") == "Register":
                    await ws.send(json.dumps({"state": INITIAL_STATE}))
                elif msg.get("action") == "Ping":
                    await ws.send(json.dumps({"Pong": ""}))
        finally:
            self._connections.remove(ws)

    async def push_update(self, patch: Dict[str, Any]) -> None:
        """Send a state delta to all connected clients."""
        payload = json.dumps({"state": patch})
        for ws in list(self._connections):
            try:
                await ws.send(payload)
            except Exception:
                pass

    async def push_raw(self, payload: str) -> None:
        """Send a raw string payload to all clients (for malformed-message testing)."""
        for ws in list(self._connections):
            try:
                await ws.send(payload)
            except Exception:
                pass

    async def start(self) -> None:
        self._server = await websockets.serve(self._handler, "127.0.0.1", self.port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()


@pytest_asyncio.fixture
async def mock_server():
    server = MockScoreboardServer()
    await server.start()
    yield server
    await server.stop()

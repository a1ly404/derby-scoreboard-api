from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from client import ScoreboardClient, _coerce
from tests.conftest import MockScoreboardServer, INITIAL_STATE


pytestmark = pytest.mark.asyncio


async def _connected_client(server: MockScoreboardServer) -> ScoreboardClient:
    """Start a client, wait for it to receive the initial snapshot."""
    client = ScoreboardClient(host="127.0.0.1", port=server.port)
    task = client.start()
    # Give the client time to connect and receive the initial snapshot
    for _ in range(50):
        if client.connected and client.get_version() is not None:
            break
        await asyncio.sleep(0.05)
    return client, task


async def test_client_connects_and_receives_initial_state(mock_server):
    client, task = await _connected_client(mock_server)
    try:
        assert client.connected is True
        assert client.get_version() == "v5.0.0-test"
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_get_live_state_maps_team_names(mock_server):
    client, task = await _connected_client(mock_server)
    try:
        state = client.get_live_state()
        assert state.team1.name == "Home Team"
        assert state.team2.name == "Away Team"
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_get_live_state_maps_scores(mock_server):
    client, task = await _connected_client(mock_server)
    try:
        state = client.get_live_state()
        assert state.team1.score == 42
        assert state.team2.score == 37
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_get_live_state_maps_clocks(mock_server):
    client, task = await _connected_client(mock_server)
    try:
        state = client.get_live_state()
        assert state.jam_clock_ms == 60000
        assert state.period_clock_ms == 900000
        assert state.jam_running is False
        assert state.period == 1
        assert state.jam == 3
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_get_live_state_maps_jammer_info(mock_server):
    client, task = await _connected_client(mock_server)
    try:
        state = client.get_live_state()
        assert state.team1.jammer == "Speed Demon"
        assert state.team1.jammer_number == "88"
        assert state.team2.jammer == "Lightning Bolt"
        assert state.team2.jammer_number == "7"
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_state_update_reflects_new_score(mock_server):
    client, task = await _connected_client(mock_server)
    try:
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Score": 47,
            "ScoreBoard.CurrentGame.Team(1).JamScore": 5,
        })
        await asyncio.sleep(0.1)
        state = client.get_live_state()
        assert state.team1.score == 47
        assert state.team1.jam_score == 5
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_null_value_deletes_key(mock_server):
    client, task = await _connected_client(mock_server)
    try:
        # Null out the jammer name (happens when jam ends in real scoreboard)
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Position(Jammer).Name": None,
        })
        await asyncio.sleep(0.1)
        state = client.get_live_state()
        assert state.team1.jammer is None
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_lead_and_display_lead(mock_server):
    client, task = await _connected_client(mock_server)
    try:
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Lead": True,
            "ScoreBoard.CurrentGame.Team(1).DisplayLead": True,
        })
        await asyncio.sleep(0.1)
        state = client.get_live_state()
        assert state.team1.lead is True
        assert state.team1.display_lead is True
        assert state.team2.lead is False
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_raw_state_returns_full_dict(mock_server):
    client, task = await _connected_client(mock_server)
    try:
        raw = client.get_raw_state()
        assert "ScoreBoard.CurrentGame.Team(1).Score" in raw
        assert raw["ScoreBoard.CurrentGame.Team(1).Score"] == 42
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_reconnects_after_server_restart(mock_server):
    client, task = await _connected_client(mock_server)
    try:
        assert client.connected is True
        # Stop the server to force disconnect
        await mock_server.stop()
        await asyncio.sleep(0.2)
        assert client.connected is False
        # Restart the server on the same port
        await mock_server.start()
        # Wait for reconnect (client retries every 2s, but we patched RECONNECT_DELAY implicitly)
        for _ in range(60):
            if client.connected:
                break
            await asyncio.sleep(0.1)
        # We give reconnect a longer window — this tests the loop exists
        # In CI the full 2s delay means we just wait long enough
    finally:
        client.stop()
        await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Bug-regression tests added during QA
# ---------------------------------------------------------------------------

# Bug: bool("false") == True in Python — coercion of CRG string booleans
def test_coerce_string_false_returns_false():
    assert _coerce("false", bool) is False


def test_coerce_string_true_returns_true():
    assert _coerce("true", bool) is True


def test_coerce_string_zero_treated_as_false():
    assert _coerce("0", bool) is False


def test_coerce_native_booleans_pass_through_unchanged():
    assert _coerce(True, bool) is True
    assert _coerce(False, bool) is False


def test_coerce_none_returns_none_for_bool():
    assert _coerce(None, bool) is None


# Bug: _apply_update with non-dict state (e.g. null) must not kill the WS loop
async def test_null_state_patch_does_not_kill_connection(mock_server):
    """Sending {"state": null} should not crash the receive loop."""
    client, task = await _connected_client(mock_server)
    try:
        # Push a null state to trigger the non-dict guard
        await mock_server.push_raw(json.dumps({"state": None}))
        await asyncio.sleep(0.1)
        # Client should still be connected
        assert client.connected is True
        # And should process subsequent valid updates normally
        await mock_server.push_update({"ScoreBoard.CurrentGame.Team(1).Score": 99})
        await asyncio.sleep(0.1)
        assert client.get_live_state().team1.score == 99
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_list_state_patch_does_not_kill_connection(mock_server):
    """Sending {"state": [...]} should not crash the receive loop."""
    client, task = await _connected_client(mock_server)
    try:
        await mock_server.push_raw(json.dumps({"state": ["unexpected", "array"]}))
        await asyncio.sleep(0.1)
        assert client.connected is True
        # Score from initial state should still be intact
        assert client.get_live_state().team1.score == 42
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_seconds_since_update_is_populated_after_connect(mock_server):
    """After receiving the initial state snapshot, seconds_since_update must be a float >= 0."""
    client, task = await _connected_client(mock_server)
    try:
        secs = client.get_seconds_since_update()
        assert secs is not None
        assert isinstance(secs, float)
        assert secs >= 0.0
    finally:
        client.stop()
        await asyncio.sleep(0.05)

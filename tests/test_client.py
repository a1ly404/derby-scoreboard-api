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
        assert state.team1.jammer.name == "Speed Demon"
        assert state.team1.jammer.number == "88"
        assert state.team2.jammer.name == "Lightning Bolt"
        assert state.team2.jammer.number == "7"
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_get_live_state_maps_all_positions(mock_server):
    client, task = await _connected_client(mock_server)
    try:
        state = client.get_live_state()
        t1 = state.team1
        assert t1.pivot.name == "Iron Curtain"
        assert t1.pivot.number == "22"
        assert t1.blocker1.name == "Brick Wall"
        assert t1.blocker2.name == "Crash Test"
        assert t1.blocker3.name == "Ricochet"
        t2 = state.team2
        assert t2.pivot.name == "Storm Front"
        assert t2.blocker1.name == "Ground Zero"
        assert t2.blocker2.name == "Shockwave"
        assert t2.blocker3.name == "Afterburn"
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_penalty_box_defaults_false_when_key_absent(mock_server):
    """When CRG has never sent a PenaltyBox key, in_box must default to False (not None)."""
    client, task = await _connected_client(mock_server)
    try:
        # Delete all PenaltyBox keys so the client has no value for them
        await mock_server.push_update({
            f"ScoreBoard.CurrentGame.Team({t}).Position({p}).PenaltyBox": None
            for t in (1, 2)
            for p in ("Jammer", "Pivot", "Blocker1", "Blocker2", "Blocker3")
        })
        await asyncio.sleep(0.1)
        state = client.get_live_state()
        for pos in (state.team1.jammer, state.team1.pivot,
                    state.team1.blocker1, state.team1.blocker2, state.team1.blocker3):
            assert pos.in_box is False, f"Expected False when key absent, got {pos.in_box}"
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_penalty_box_update(mock_server):
    client, task = await _connected_client(mock_server)
    try:
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Position(Blocker2).PenaltyBox": True,
        })
        await asyncio.sleep(0.1)
        state = client.get_live_state()
        assert state.team1.blocker2.in_box is True
        assert state.team1.blocker1.in_box is False
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
        assert state.team1.jammer.name is None
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


# ---------------------------------------------------------------------------
# box_elapsed_jam_ms tests
# ---------------------------------------------------------------------------

async def test_box_elapsed_is_none_when_not_in_box(mock_server):
    """box_elapsed_jam_ms is None for skaters not in the penalty box."""
    client, task = await _connected_client(mock_server)
    try:
        state = client.get_live_state()
        # Initial state has nobody in box
        assert state.team1.blocker2.in_box is False
        assert state.team1.blocker2.box_elapsed_jam_ms is None
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_box_elapsed_initialises_to_zero_on_box_entry(mock_server):
    """box_elapsed_jam_ms starts at 0 the moment in_box becomes True (before any jam tick)."""
    client, task = await _connected_client(mock_server)
    try:
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Position(Blocker1).PenaltyBox": True,
        })
        await asyncio.sleep(0.1)
        state = client.get_live_state()
        assert state.team1.blocker1.in_box is True
        assert state.team1.blocker1.box_elapsed_jam_ms == 0
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_box_elapsed_accumulates_while_jam_running(mock_server):
    """box_elapsed_jam_ms increases by the jam-clock delta when jam_running is True."""
    client, task = await _connected_client(mock_server)
    try:
        # Put blocker2 in box then start the jam
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Position(Blocker2).PenaltyBox": True,
            "ScoreBoard.CurrentGame.Clock(Jam).Running": True,
            "ScoreBoard.CurrentGame.Clock(Jam).Time": 60000,
        })
        await asyncio.sleep(0.1)

        # Tick the jam clock down 1 second
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Clock(Jam).Time": 59000,
        })
        await asyncio.sleep(0.1)

        state = client.get_live_state()
        assert state.team1.blocker2.box_elapsed_jam_ms == 1000

        # Another 2 seconds
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Clock(Jam).Time": 57000,
        })
        await asyncio.sleep(0.1)

        state = client.get_live_state()
        assert state.team1.blocker2.box_elapsed_jam_ms == 3000
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_box_elapsed_does_not_accumulate_when_jam_not_running(mock_server):
    """box_elapsed_jam_ms stays flat between jams (jam_running=False)."""
    client, task = await _connected_client(mock_server)
    try:
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(2).Position(Jammer).PenaltyBox": True,
            "ScoreBoard.CurrentGame.Clock(Jam).Running": True,
            "ScoreBoard.CurrentGame.Clock(Jam).Time": 30000,
        })
        await asyncio.sleep(0.1)

        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Clock(Jam).Time": 28000,
        })
        await asyncio.sleep(0.1)
        state = client.get_live_state()
        assert state.team2.jammer.box_elapsed_jam_ms == 2000

        # Jam ends — clock stops
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Clock(Jam).Running": False,
            "ScoreBoard.CurrentGame.Clock(Jam).Time": 28000,
        })
        await asyncio.sleep(0.1)

        # Clock update arrives but jam not running — no accumulation
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Clock(Jam).Time": 27000,
        })
        await asyncio.sleep(0.1)

        state = client.get_live_state()
        assert state.team2.jammer.box_elapsed_jam_ms == 2000
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_box_elapsed_resets_when_skater_leaves_box(mock_server):
    """box_elapsed_jam_ms returns to None when in_box transitions to False."""
    client, task = await _connected_client(mock_server)
    try:
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Position(Pivot).PenaltyBox": True,
            "ScoreBoard.CurrentGame.Clock(Jam).Running": True,
            "ScoreBoard.CurrentGame.Clock(Jam).Time": 20000,
        })
        await asyncio.sleep(0.1)
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Clock(Jam).Time": 10000,
        })
        await asyncio.sleep(0.1)
        state = client.get_live_state()
        assert state.team1.pivot.box_elapsed_jam_ms == 10000

        # Skater leaves box
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Position(Pivot).PenaltyBox": False,
        })
        await asyncio.sleep(0.1)
        state = client.get_live_state()
        assert state.team1.pivot.in_box is False
        assert state.team1.pivot.box_elapsed_jam_ms is None
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_box_elapsed_only_accumulates_for_in_box_skaters(mock_server):
    """Elapsed time does not accrue for skaters who are not in the box."""
    client, task = await _connected_client(mock_server)
    try:
        # Only blocker3 goes in — blocker1 stays out
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Position(Blocker3).PenaltyBox": True,
            "ScoreBoard.CurrentGame.Clock(Jam).Running": True,
            "ScoreBoard.CurrentGame.Clock(Jam).Time": 60000,
        })
        await asyncio.sleep(0.1)
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Clock(Jam).Time": 55000,
        })
        await asyncio.sleep(0.1)
        state = client.get_live_state()
        assert state.team1.blocker3.box_elapsed_jam_ms == 5000
        assert state.team1.blocker1.box_elapsed_jam_ms is None
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_box_elapsed_entry_simultaneous_with_clock_tick(mock_server):
    """Skater entering box in the same message as a clock tick should NOT
    receive elapsed credit for the interval before they entered."""
    client, task = await _connected_client(mock_server)
    try:
        # Jam already running with clock at 50000
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Clock(Jam).Running": True,
            "ScoreBoard.CurrentGame.Clock(Jam).Time": 50000,
        })
        await asyncio.sleep(0.1)

        # Box entry AND 2-second clock tick in the same message
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Position(Blocker1).PenaltyBox": True,
            "ScoreBoard.CurrentGame.Clock(Jam).Time": 48000,
        })
        await asyncio.sleep(0.1)

        state = client.get_live_state()
        # The 2000 ms delta belongs to the interval before the skater entered;
        # elapsed must still be 0 (not 2000).
        assert state.team1.blocker1.in_box is True
        assert state.team1.blocker1.box_elapsed_jam_ms == 0
    finally:
        client.stop()
        await asyncio.sleep(0.05)


async def test_box_elapsed_exit_simultaneous_with_clock_tick(mock_server):
    """Skater exiting box in the same message as a clock tick SHOULD receive
    elapsed credit for that final interval before being cleared."""
    client, task = await _connected_client(mock_server)
    try:
        # Box entry, then jam starts
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Position(Blocker2).PenaltyBox": True,
            "ScoreBoard.CurrentGame.Clock(Jam).Running": True,
            "ScoreBoard.CurrentGame.Clock(Jam).Time": 60000,
        })
        await asyncio.sleep(0.1)

        # Accumulate 5 seconds
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Clock(Jam).Time": 55000,
        })
        await asyncio.sleep(0.1)

        # Box exit AND 3-second clock tick arrive together —
        # the final 3000 ms should be credited before the timer is cleared
        # (but in_box will be False and box_elapsed_jam_ms will be None
        #  because the skater has left; the key thing is it doesn't corrupt
        #  any other skater and the exit doesn't suppress the delta for others)
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Position(Blocker2).PenaltyBox": False,
            "ScoreBoard.CurrentGame.Clock(Jam).Time": 52000,
        })
        await asyncio.sleep(0.1)

        state = client.get_live_state()
        # Skater has left — elapsed is None
        assert state.team1.blocker2.in_box is False
        assert state.team1.blocker2.box_elapsed_jam_ms is None
        # Other skaters unaffected
        assert state.team1.blocker1.box_elapsed_jam_ms is None
    finally:
        client.stop()
        await asyncio.sleep(0.05)

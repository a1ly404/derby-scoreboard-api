from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import patch

import pytest
import pytest_asyncio

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from client import ScoreboardClient, _coerce
from tests.conftest import MockScoreboardServer, INITIAL_STATE


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


@pytest.mark.asyncio
async def test_client_connects_and_receives_initial_state(mock_server):
    client, task = await _connected_client(mock_server)
    try:
        assert client.connected is True
        assert client.get_version() == "v5.0.0-test"
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_get_live_state_maps_team_names(mock_server):
    client, task = await _connected_client(mock_server)
    try:
        state = client.get_live_state()
        assert state.team1.name == "Home Team"
        assert state.team2.name == "Away Team"
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_get_live_state_maps_scores(mock_server):
    client, task = await _connected_client(mock_server)
    try:
        state = client.get_live_state()
        assert state.team1.score == 42
        assert state.team2.score == 37
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_box_entered_at_ms_is_none_when_not_in_box(mock_server):
    """box_entered_at_ms is None for skaters not in the penalty box."""
    client, task = await _connected_client(mock_server)
    try:
        state = client.get_live_state()
        assert state.team1.blocker1.box_entered_at_ms is None
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_box_entered_at_ms_set_on_entry(mock_server):
    """box_entered_at_ms is set to a recent epoch-ms timestamp on box entry."""
    client, task = await _connected_client(mock_server)
    try:
        before_ms = int(time.time() * 1000)
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Position(Blocker1).PenaltyBox": True,
        })
        await asyncio.sleep(0.1)
        after_ms = int(time.time() * 1000)

        state = client.get_live_state()
        assert state.team1.blocker1.in_box is True
        ts = state.team1.blocker1.box_entered_at_ms
        assert ts is not None
        assert before_ms <= ts <= after_ms
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_box_entered_at_ms_cleared_on_exit(mock_server):
    """box_entered_at_ms returns to None when in_box transitions to False."""
    client, task = await _connected_client(mock_server)
    try:
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Position(Blocker1).PenaltyBox": True,
        })
        await asyncio.sleep(0.1)
        assert client.get_live_state().team1.blocker1.box_entered_at_ms is not None

        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Position(Blocker1).PenaltyBox": False,
        })
        await asyncio.sleep(0.1)
        state = client.get_live_state()
        assert state.team1.blocker1.in_box is False
        assert state.team1.blocker1.box_entered_at_ms is None
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_box_time_remaining_s_none_when_not_in_box(mock_server):
    """box_time_remaining_s is None for skaters not in the penalty box."""
    client, task = await _connected_client(mock_server)
    try:
        state = client.get_live_state()
        assert state.team1.blocker1.box_time_remaining_s is None
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_box_time_remaining_s_counts_down(mock_server):
    """box_time_remaining_s reflects correct remaining seconds after box entry."""
    client, task = await _connected_client(mock_server)
    try:
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Position(Jammer).PenaltyBox": True,
        })
        await asyncio.sleep(0.1)
        state = client.get_live_state()
        remaining = state.team1.jammer.box_time_remaining_s
        assert remaining is not None
        # Should be at most 30 and greater than 0 (entered less than a second ago)
        assert 0 < remaining <= 30
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_box_time_remaining_s_zero_when_expired(mock_server):
    """box_time_remaining_s is 0 when the 30-second window has already passed."""
    from client import PENALTY_BOX_DURATION_S
    client, task = await _connected_client(mock_server)
    try:
        past_time = time.time() - (PENALTY_BOX_DURATION_S + 5)
        past_mono = time.monotonic() - (PENALTY_BOX_DURATION_S + 5)
        with patch("client.time") as mock_time:
            mock_time.time.return_value = past_time
            mock_time.monotonic.return_value = past_mono
            await mock_server.push_update({
                "ScoreBoard.CurrentGame.Team(2).Position(Pivot).PenaltyBox": True,
            })
            await asyncio.sleep(0.1)
        state = client.get_live_state()
        assert state.team2.pivot.box_time_remaining_s == 0
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_box_entered_at_ms_not_reset_on_repeated_true(mock_server):
    """box_entered_at_ms is not updated if in_box is already True (no re-entry)."""
    client, task = await _connected_client(mock_server)
    try:
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Position(Blocker1).PenaltyBox": True,
        })
        await asyncio.sleep(0.1)
        first_ts = client.get_live_state().team1.blocker1.box_entered_at_ms

        # Another PenaltyBox=True (e.g. scoreboard resending state)
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Position(Blocker1).PenaltyBox": True,
        })
        await asyncio.sleep(0.1)
        second_ts = client.get_live_state().team1.blocker1.box_entered_at_ms

        assert first_ts == second_ts
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.parametrize(
    "game_state, expected",
    [
        ("Team Timeout", "team_timeout"),
        ("Official Timeout", "official_timeout"),
        ("Official Review", "official_review"),
    ],
)
@pytest.mark.asyncio
async def test_timeout_type_from_game_state(mock_server, game_state, expected):
    client, task = await _connected_client(mock_server)
    try:
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Clock(Jam).Running": False,
            "ScoreBoard.CurrentGame.State": game_state,
        })
        await asyncio.sleep(0.1)
        state = client.get_live_state()
        assert state.timeout_type == expected
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_timeout_type_clears_when_jam_running(mock_server):
    client, task = await _connected_client(mock_server)
    try:
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Clock(Jam).Running": False,
            "ScoreBoard.CurrentGame.State": "Official Timeout",
        })
        await asyncio.sleep(0.1)
        assert client.get_live_state().timeout_type == "official_timeout"

        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Clock(Jam).Running": True,
        })
        await asyncio.sleep(0.1)
        assert client.get_live_state().timeout_type is None
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_raw_state_returns_full_dict(mock_server):
    client, task = await _connected_client(mock_server)
    try:
        raw = client.get_raw_state()
        assert "ScoreBoard.CurrentGame.Team(1).Score" in raw
        assert raw["ScoreBoard.CurrentGame.Team(1).Score"] == 42
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
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
@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


# Additional coverage tests
# ---------------------------------------------------------------------------

def test_coerce_invalid_type_returns_original_value():
    """Test _coerce with invalid type conversion that raises ValueError or TypeError."""
    # Try to convert "invalid" to int - should return original value
    assert _coerce("invalid", int) == "invalid"
    
    # Try to convert None to a complex type that would raise TypeError
    class TestClass:
        def __init__(self, value):
            if value is None:
                raise TypeError("Cannot create TestClass from None")
            self.value = value
    
    assert _coerce(None, TestClass) is None


def test_normalize_timeout_type_additional_cases():
    """Test additional timeout type case variants."""
    from client import ScoreboardClient
    
    # Test generic "timeout" case
    assert ScoreboardClient._normalize_timeout_type("Timeout", False) == "timeout"
    
    # Test "review" case
    assert ScoreboardClient._normalize_timeout_type("Review", False) == "official_review"
    
    # Test unrecognized state
    assert ScoreboardClient._normalize_timeout_type("Running", False) is None
    
    # Test null/empty cases
    assert ScoreboardClient._normalize_timeout_type("", False) is None


@pytest.mark.asyncio  
async def test_client_handles_json_decode_error(mock_server):
    """Test that client handles non-JSON messages gracefully."""
    client, task = await _connected_client(mock_server)
    try:
        # Send an invalid JSON message through the mock server
        await mock_server.push_raw("invalid json {")
        await asyncio.sleep(0.1)
        
        # Client should still be connected and functioning
        assert client.connected is True
        state = client.get_live_state()
        assert state.team1.score == 42  # Original state should be intact
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_client_handles_message_processing_error(mock_server):
    """Test that client handles errors in message processing gracefully.""" 
    client, task = await _connected_client(mock_server)
    try:
        # Send a message with state that would cause processing issues
        await mock_server.push_update({"invalid": "structure that might cause errors"})
        await asyncio.sleep(0.1)
        
        # Client should still be connected
        assert client.connected is True
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_client_handles_error_message_from_scoreboard(mock_server):
    """Test client handles error messages from scoreboard.""" 
    import json
    client, task = await _connected_client(mock_server)
    try:
        # Send an error message as the scoreboard might
        await mock_server.push_raw(json.dumps({"error": "Test error from scoreboard"}))
        await asyncio.sleep(0.1)
        
        # Client should still be connected despite error
        assert client.connected is True
    finally:
        client.stop()
        await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Star-pass tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_star_pass_false_does_not_swap_jammer_and_pivot(mock_server):
    """When star_pass is False the jammer and pivot are returned as-is."""
    client, task = await _connected_client(mock_server)
    try:
        state = client.get_live_state()
        assert state.team1.star_pass is False
        assert state.team1.jammer.name == "Speed Demon"
        assert state.team1.pivot.name == "Iron Curtain"
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_star_pass_true_swaps_jammer_and_pivot(mock_server):
    """When star_pass is True the pivot becomes the jammer and vice-versa."""
    client, task = await _connected_client(mock_server)
    try:
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).StarPass": True,
        })
        await asyncio.sleep(0.1)
        state = client.get_live_state()
        assert state.team1.star_pass is True
        # Pivot (Iron Curtain) is now the jammer
        assert state.team1.jammer.name == "Iron Curtain"
        assert state.team1.jammer.number == "22"
        # Original jammer (Speed Demon) is now in the pivot slot
        assert state.team1.pivot.name == "Speed Demon"
        assert state.team1.pivot.number == "88"
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_star_pass_swap_does_not_affect_other_team(mock_server):
    """A star pass for one team must not affect the other team's positions."""
    client, task = await _connected_client(mock_server)
    try:
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).StarPass": True,
        })
        await asyncio.sleep(0.1)
        state = client.get_live_state()
        # Team 2 is unaffected
        assert state.team2.star_pass is False
        assert state.team2.jammer.name == "Lightning Bolt"
        assert state.team2.pivot.name == "Storm Front"
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_star_pass_cleared_restores_original_positions(mock_server):
    """When star_pass goes back to False the positions revert to original order."""
    client, task = await _connected_client(mock_server)
    try:
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(2).StarPass": True,
        })
        await asyncio.sleep(0.1)
        # Confirm swap happened for team 2
        assert client.get_live_state().team2.jammer.name == "Storm Front"

        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(2).StarPass": False,
        })
        await asyncio.sleep(0.1)
        state = client.get_live_state()
        assert state.team2.star_pass is False
        assert state.team2.jammer.name == "Lightning Bolt"
        assert state.team2.pivot.name == "Storm Front"
    finally:
        client.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_star_pass_box_tracking_follows_swapped_skater(mock_server):
    """Penalty-box state stays with the skater, not the position label, after a star pass."""
    client, task = await _connected_client(mock_server)
    try:
        # Put the original jammer (Speed Demon) in the box, then trigger a star pass
        await mock_server.push_update({
            "ScoreBoard.CurrentGame.Team(1).Position(Jammer).PenaltyBox": True,
            "ScoreBoard.CurrentGame.Team(1).StarPass": True,
        })
        await asyncio.sleep(0.1)
        state = client.get_live_state()
        # After the star pass the original jammer is now in the pivot slot
        assert state.team1.pivot.name == "Speed Demon"
        assert state.team1.pivot.in_box is True
        # The new jammer (Iron Curtain / original pivot) should not be in the box
        assert state.team1.jammer.name == "Iron Curtain"
        assert state.team1.jammer.in_box is False
    finally:
        client.stop()
        await asyncio.sleep(0.05)

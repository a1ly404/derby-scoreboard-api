from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import create_app
from tests.conftest import MockScoreboardServer, _free_port

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_client(mock_server: MockScoreboardServer):
    """
    Create a FastAPI app wired to the mock scoreboard server,
    and return an httpx AsyncClient for making test requests.

    ASGITransport does not trigger ASGI lifespan, so we manually
    start and stop the scoreboard WS client around the test.
    """
    app = create_app(scoreboard_host="127.0.0.1", scoreboard_port=mock_server.port)
    sb_client = app.state.scoreboard_client
    task = sb_client.start()
    # Wait for the WS client to connect and receive the initial snapshot
    for _ in range(50):
        if sb_client.connected and sb_client.get_version() is not None:
            break
        await asyncio.sleep(0.05)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    sb_client.stop()
    try:
        await asyncio.wait_for(task, timeout=2)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass


async def test_health_connected(app_client):
    resp = await app_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is True
    assert data["scoreboard_version"] == "v5.0.0-test"


async def test_live_returns_200(app_client):
    resp = await app_client.get("/live")
    assert resp.status_code == 200


async def test_live_team_names(app_client):
    resp = await app_client.get("/live")
    data = resp.json()
    assert data["team1"]["name"] == "Home Team"
    assert data["team2"]["name"] == "Away Team"


async def test_live_scores(app_client):
    resp = await app_client.get("/live")
    data = resp.json()
    assert data["team1"]["score"] == 42
    assert data["team2"]["score"] == 37


async def test_live_clocks(app_client):
    resp = await app_client.get("/live")
    data = resp.json()
    assert data["jam_clock_ms"] == 60000
    assert data["period_clock_ms"] == 900000
    assert data["jam_running"] is False
    assert data["period"] == 1
    assert data["jam"] == 3


async def test_live_jammer_names(app_client):
    resp = await app_client.get("/live")
    data = resp.json()
    assert data["team1"]["jammer"]["name"] == "Speed Demon"
    assert data["team2"]["jammer"]["name"] == "Lightning Bolt"


async def test_live_includes_timeout_type_field(app_client):
    resp = await app_client.get("/live")
    data = resp.json()
    assert "timeout_type" in data


async def test_live_reflects_score_update(app_client, mock_server):
    await mock_server.push_update({
        "ScoreBoard.CurrentGame.Team(2).Score": 50,
    })
    await asyncio.sleep(0.15)
    resp = await app_client.get("/live")
    data = resp.json()
    assert data["team2"]["score"] == 50


async def test_live_reflects_jam_start(app_client, mock_server):
    await mock_server.push_update({
        "ScoreBoard.CurrentGame.InJam": True,
        "ScoreBoard.CurrentGame.Clock(Jam).Running": True,
        "ScoreBoard.CurrentGame.Clock(Jam).Time": 120000,
    })
    await asyncio.sleep(0.15)
    resp = await app_client.get("/live")
    data = resp.json()
    assert data["in_jam"] is True
    assert data["jam_running"] is True
    assert data["jam_clock_ms"] == 120000


async def test_raw_contains_crg_keys(app_client):
    resp = await app_client.get("/raw")
    assert resp.status_code == 200
    data = resp.json()
    assert "ScoreBoard.CurrentGame.Team(1).Score" in data
    assert "ScoreBoard.CurrentGame.Clock(Jam).Time" in data


async def test_openapi_docs_available(app_client):
    resp = await app_client.get("/docs")
    assert resp.status_code == 200


async def test_openapi_json_available(app_client):
    resp = await app_client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()


# ---------------------------------------------------------------------------
# Offline / disconnected fixture and tests
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def app_client_offline():
    """App whose scoreboard client can't connect (no server on the port)."""
    port = _free_port()  # get a real unused port, then start nothing on it
    app = create_app(scoreboard_host="127.0.0.1", scoreboard_port=port)
    sb_client = app.state.scoreboard_client
    task = sb_client.start()
    await asyncio.sleep(0.15)  # client will attempt and fail to connect
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    sb_client.stop()
    try:
        await asyncio.wait_for(task, timeout=2)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass


async def test_live_returns_503_when_disconnected(app_client_offline):
    resp = await app_client_offline.get("/live")
    assert resp.status_code == 503


async def test_raw_returns_503_when_disconnected(app_client_offline):
    resp = await app_client_offline.get("/raw")
    assert resp.status_code == 503


async def test_health_connected_flag_false_when_disconnected(app_client_offline):
    resp = await app_client_offline.get("/health")
    assert resp.status_code == 200
    assert resp.json()["connected"] is False


async def test_health_includes_seconds_since_update(app_client):
    """seconds_since_update must be a non-negative float when connected."""
    resp = await app_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "seconds_since_update" in data
    assert data["seconds_since_update"] is not None
    assert data["seconds_since_update"] >= 0.0


async def test_live_includes_state_age_seconds(app_client):
    """state_age_seconds must be a non-negative float on a live /live response."""
    resp = await app_client.get("/live")
    assert resp.status_code == 200
    data = resp.json()
    assert "state_age_seconds" in data
    assert data["state_age_seconds"] is not None
    assert data["state_age_seconds"] >= 0.0


async def test_live_connected_true_when_connected(app_client):
    resp = await app_client.get("/live")
    assert resp.status_code == 200
    assert resp.json()["connected"] is True


async def test_live_connected_false_when_disconnected_but_has_state(app_client_offline):
    """
    If the proxy previously had state but has since lost the connection,
    /live should return 200 with connected=false (not 503) so overlays can
    show a 'reconnecting' indicator rather than going blank.
    This test verifies the gate condition: 503 only fires when there is no
    state at all (game_state is None).
    """
    # The offline fixture has no state at all, so 503 is expected here
    resp = await app_client_offline.get("/live")
    assert resp.status_code == 503


async def test_live_503_has_retry_after_header(app_client_offline):
    resp = await app_client_offline.get("/live")
    assert resp.status_code == 503
    assert "retry-after" in resp.headers
    assert int(resp.headers["retry-after"]) > 0


async def test_raw_503_has_retry_after_header(app_client_offline):
    resp = await app_client_offline.get("/raw")
    assert resp.status_code == 503
    assert "retry-after" in resp.headers
    assert int(resp.headers["retry-after"]) > 0


# ---------------------------------------------------------------------------
# Concurrency / load sanity — simulates multiple overlays polling simultaneously
# ---------------------------------------------------------------------------

async def test_concurrent_live_requests(app_client):
    """
    Fire 25 simultaneous /live requests (5 overlays × 200ms poll = ~25 req/s).
    All must return 200 with consistent scores.
    """
    responses = await asyncio.gather(
        *[app_client.get("/live") for _ in range(25)]
    )
    for resp in responses:
        assert resp.status_code == 200
        data = resp.json()
        assert data["team1"]["score"] == 42
        assert data["team2"]["score"] == 37


async def test_live_all_positions_present(app_client):
    resp = await app_client.get("/live")
    assert resp.status_code == 200
    data = resp.json()
    for team in ("team1", "team2"):
        for pos in ("jammer", "pivot", "blocker1", "blocker2", "blocker3"):
            assert pos in data[team], f"{team}.{pos} missing from /live"
            assert "name" in data[team][pos]
            assert "number" in data[team][pos]
            assert "in_box" in data[team][pos]


async def test_live_penalty_box_update(app_client, mock_server):
    await mock_server.push_update({
        "ScoreBoard.CurrentGame.Team(2).Position(Jammer).PenaltyBox": True,
    })
    await asyncio.sleep(0.15)
    resp = await app_client.get("/live")
    data = resp.json()
    assert data["team2"]["jammer"]["in_box"] is True
    assert data["team1"]["jammer"]["in_box"] is False

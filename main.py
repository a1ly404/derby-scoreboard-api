from __future__ import annotations

import argparse
import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from client import ScoreboardClient
from models import HealthState, LiveState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the WS client background task on startup, stop on shutdown."""
    client = app.state.scoreboard_client
    task = client.start()
    logger.info(
        "Scoreboard WS client started -> ws://%s:%d/WS/",
        client.host,
        client.port,
    )
    yield
    client.stop()
    try:
        await asyncio.wait_for(task, timeout=3)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    logger.info("Scoreboard WS client stopped")


def create_app(scoreboard_host: str = "localhost", scoreboard_port: int = 8000) -> FastAPI:
    app = FastAPI(
        title="Derby Scoreboard API",
        description=(
            "Lightweight REST proxy for the CRG scoreboard WebSocket. "
            "Connect to /live for real-time game state. "
            "Visit /docs for the full OpenAPI reference."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    client = ScoreboardClient(host=scoreboard_host, port=scoreboard_port)
    app.state.scoreboard_client = client

    @app.get(
        "/live",
        response_model=LiveState,
        summary="Live game state",
        description=(
            "Returns the current game state mapped to clean, human-readable fields. "
            "Poll this endpoint as frequently as needed — 200ms is sufficient for smooth clock display. "
            "Clock values are in **milliseconds**."
        ),
    )
    async def get_live(request: Request) -> LiveState:
        return request.app.state.scoreboard_client.get_live_state()

    @app.get(
        "/raw",
        summary="Raw scoreboard state",
        description=(
            "Returns the full flat key→value state dict as received from the scoreboard WebSocket. "
            "Useful for discovering available fields or debugging. "
            "Keys use the CRG WS path format, e.g. `ScoreBoard.CurrentGame.Clock(Jam).Time`."
        ),
    )
    async def get_raw(request: Request) -> dict:
        return request.app.state.scoreboard_client.get_raw_state()

    @app.get(
        "/health",
        response_model=HealthState,
        summary="Connection health",
        description="Reports whether the proxy is currently connected to the scoreboard WebSocket.",
    )
    async def get_health(request: Request) -> HealthState:
        c = request.app.state.scoreboard_client
        return HealthState(
            connected=c.connected,
            scoreboard_version=c.get_version(),
        )

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Derby Scoreboard API — REST proxy for the CRG scoreboard WebSocket"
    )
    parser.add_argument(
        "--scoreboard-host",
        default="localhost",
        help="Hostname/IP of the CRG scoreboard (default: localhost)",
    )
    parser.add_argument(
        "--scoreboard-port",
        type=int,
        default=8000,
        help="Port the CRG scoreboard is running on (default: 8000)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind the API server to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5001,
        help="Port to serve the API on (default: 5001)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    app = create_app(
        scoreboard_host=args.scoreboard_host,
        scoreboard_port=args.scoreboard_port,
    )
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )

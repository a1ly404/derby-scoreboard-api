from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Union

import httpx
import uvicorn
from deploy import DEFAULT_BACKEND_PORT, read_active_backend_port
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


def _copy_response_headers(response: httpx.Response) -> dict[str, str]:
    excluded = {"content-encoding", "transfer-encoding", "connection", "keep-alive"}
    return {k: v for k, v in response.headers.items() if k.lower() not in excluded}


def create_proxy_app(
    state_file: str | Path,
    backend_host: str = "127.0.0.1",
    default_backend_port: int = DEFAULT_BACKEND_PORT,
) -> FastAPI:
    state_path = Path(state_file)

    app = FastAPI(
        title="Derby Scoreboard API Proxy",
        description="Stable front-door reverse proxy for blue/green backend swap",
        version="1.0.0",
    )

    @app.get("/_proxy/health")
    async def proxy_health() -> dict[str, Union[int, str]]:
        active_port = read_active_backend_port(state_path, default_backend_port)
        return {"status": "ok", "active_backend_port": active_port}

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    )
    async def reverse_proxy(path: str, request: Request) -> Response:
        active_port = read_active_backend_port(state_path, default_backend_port)
        target_url = f"http://{backend_host}:{active_port}/{path}"

        body = await request.body()
        req_headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in {"host", "connection", "content-length"}
        }

        timeout = httpx.Timeout(10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                upstream = await client.request(
                    method=request.method,
                    url=target_url,
                    params=request.query_params,
                    content=body,
                    headers=req_headers,
                )
        except httpx.HTTPError as exc:
            logger.warning("Proxy upstream error for %s: %s", target_url, exc)
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "upstream backend unavailable",
                    "active_backend_port": active_port,
                },
            )

        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=_copy_response_headers(upstream),
            media_type=upstream.headers.get("content-type"),
        )

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reverse proxy for zero-downtime Derby Scoreboard API backend swaps"
    )
    parser.add_argument(
        "--state-file",
        default="runtime/active_backend_port.txt",
        help="Path to active backend port state file",
    )
    parser.add_argument(
        "--backend-host",
        default="127.0.0.1",
        help="Backend host for proxied API instances",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind the proxy listener to",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5001,
        help="Port to expose the stable proxy on",
    )
    parser.add_argument(
        "--default-backend-port",
        type=int,
        default=DEFAULT_BACKEND_PORT,
        help="Fallback backend port if state file is missing/invalid",
    )
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args()
    app = create_proxy_app(
        state_file=args.state_file,
        backend_host=args.backend_host,
        default_backend_port=args.default_backend_port,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")

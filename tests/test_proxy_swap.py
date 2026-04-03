from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
from multiprocessing import Process
from pathlib import Path

import requests
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from deploy import pick_standby_port, read_active_backend_port, write_active_backend_port
from proxy import create_proxy_app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _backend_app(name: str) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"instance": name}

    return app


def _run_backend(port: int, name: str) -> None:
    uvicorn.run(_backend_app(name), host="127.0.0.1", port=port, log_level="warning")


def _wait_for_health(url: str, timeout_sec: float = 5.0) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=0.5)
            if resp.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.05)
    raise RuntimeError(f"Timed out waiting for {url}")


def test_pick_standby_port_toggles_between_ports():
    assert pick_standby_port(5002) == 5003
    assert pick_standby_port(5003) == 5002
    assert pick_standby_port(9999) == 5002


def test_active_backend_port_roundtrip(tmp_path: Path):
    state_file = tmp_path / "active_backend_port.txt"
    assert read_active_backend_port(state_file, default_port=5002) == 5002

    write_active_backend_port(state_file, 5003)
    assert read_active_backend_port(state_file, default_port=5002) == 5003


def test_proxy_swap_keeps_requests_served_without_503():
    port_a = _free_port()
    port_b = _free_port()

    proc_a = Process(target=_run_backend, args=(port_a, "A"), daemon=True)
    proc_a.start()

    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / "active_backend_port.txt"
        write_active_backend_port(state_file, port_a)

        _wait_for_health(f"http://127.0.0.1:{port_a}/health")

        proxy_app = create_proxy_app(state_file=state_file, backend_host="127.0.0.1")
        client = TestClient(proxy_app)

        seen_instances: list[str] = []
        failures: list[int] = []
        done = threading.Event()

        def poll_proxy() -> None:
            while not done.is_set():
                r = client.get("/health")
                if r.status_code != 200:
                    failures.append(r.status_code)
                else:
                    seen_instances.append(r.json().get("instance", ""))
                time.sleep(0.02)

        poller = threading.Thread(target=poll_proxy, daemon=True)
        poller.start()

        time.sleep(0.2)

        proc_b = Process(target=_run_backend, args=(port_b, "B"), daemon=True)
        proc_b.start()
        try:
            _wait_for_health(f"http://127.0.0.1:{port_b}/health")

            write_active_backend_port(state_file, port_b)
            time.sleep(0.2)

            proc_a.terminate()
            proc_a.join(timeout=3)

            time.sleep(0.2)
        finally:
            done.set()
            poller.join(timeout=2)
            proc_b.terminate()
            proc_b.join(timeout=3)

        assert not failures, f"Proxy returned non-200 responses: {failures}"
        assert "A" in seen_instances
        assert "B" in seen_instances

from __future__ import annotations

from pathlib import Path

DEFAULT_BACKEND_PORT = 5002
BACKEND_PORTS = (5002, 5003)


def read_active_backend_port(state_file: Path, default_port: int = DEFAULT_BACKEND_PORT) -> int:
    if not state_file.exists():
        return default_port

    raw = state_file.read_text(encoding="utf-8").strip()
    if not raw:
        return default_port

    try:
        return int(raw)
    except ValueError:
        return default_port


def write_active_backend_port(state_file: Path, port: int) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = state_file.with_suffix(state_file.suffix + ".tmp")
    tmp_file.write_text(str(port), encoding="utf-8")
    tmp_file.replace(state_file)


def pick_standby_port(active_port: int, ports: tuple[int, int] = BACKEND_PORTS) -> int:
    if active_port == ports[0]:
        return ports[1]
    return ports[0]

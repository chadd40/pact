"""PyInstaller/Tauri entry point: run the FastAPI app under uvicorn on a fixed
local port. Pure config resolution is split out so it can be unit-tested without
binding a socket."""
from __future__ import annotations

import os
from typing import Mapping


def _server_config(env: Mapping[str, str] | None = None) -> dict:
    env = env or {}
    host = env.get("PACT_HOST", "127.0.0.1")
    raw = env.get("PACT_PORT", "8000")
    try:
        port = int(raw)
    except ValueError:
        raise ValueError(f"PACT_PORT must be an integer, got {raw!r}") from None
    return {"host": host, "port": port}


def main() -> None:  # pragma: no cover - starts a real server
    # Signal the bundling/host layer that, once started, the app should print a
    # readiness line from its lifespan (see pact.main).
    os.environ.setdefault("PACT_EMIT_READY", "1")
    import uvicorn

    from pact.main import app

    cfg = _server_config(os.environ)
    uvicorn.run(app, host=cfg["host"], port=cfg["port"], log_level="info")


if __name__ == "__main__":  # pragma: no cover
    main()

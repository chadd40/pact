from datetime import datetime, timezone

import httpx
import pytest

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock
from pact.config import Settings
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


OWNER = "agent-owner@example.com"


def _build_app(tmp_path, *, auth_mode: str = "local_dev"):
    clock = FixedClock(datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc))
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    settings = Settings(auth_mode=auth_mode)
    app = create_app(
        repo,
        TestLLMProvider(),
        TestLinkProvider(),
        TokenStore(),
        clock,
        settings,
    )
    return app, repo, clock


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


@pytest.mark.anyio
async def test_connector_health_reports_missing_token_and_mcp_command(tmp_path):
    app, _repo, _clock = _build_app(tmp_path)

    async with _client(app) as client:
        response = await client.get("/api/connectors/health", params={"owner": OWNER})

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["owner"] == OWNER
    assert data["agent_token"]["status"] == "missing"
    assert data["worker"]["status"] == "offline"

    mcp = next(conn for conn in data["connectors"] if conn["key"] == "mcp")
    assert mcp["status"] == "needs_token"
    assert "pact mcp" in mcp["command"]
    assert "<agent-token>" in mcp["command"]
    assert data["mcp"]["server_name"] == "pact"


@pytest.mark.anyio
async def test_connector_health_reports_configured_sidecar_base_url(tmp_path, monkeypatch):
    monkeypatch.setenv("PACT_HOST", "127.0.0.1")
    monkeypatch.setenv("PACT_PORT", "8042")
    app, _repo, _clock = _build_app(tmp_path)

    async with _client(app) as client:
        response = await client.get("/api/connectors/health", params={"owner": OWNER})

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["runtime"]["base_url"] == "http://127.0.0.1:8042"
    assert "http://127.0.0.1:8042" in data["mcp"]["command"]


@pytest.mark.anyio
async def test_connector_health_uses_token_prefix_and_worker_heartbeat_without_leaking_token(tmp_path):
    app, repo, clock = _build_app(tmp_path)

    async with _client(app) as client:
        minted = await client.post("/api/account/agent-token", json={"owner": OWNER})
        assert minted.status_code == 200, minted.text
        raw_token = minted.json()["token"]

        # A worker poll is the existing liveness signal.
        repo.mark_worker_seen(clock.now())
        response = await client.get("/api/connectors/health", params={"owner": OWNER})

    assert response.status_code == 200, response.text
    data = response.json()
    assert raw_token not in response.text
    assert data["agent_token"]["status"] == "ready"
    assert data["agent_token"]["token_prefix"] == raw_token[:12]
    assert data["worker"]["status"] == "online"
    assert data["capabilities"]["text"] is True
    assert data["capabilities"]["vision"] is True

    mcp = next(conn for conn in data["connectors"] if conn["key"] == "mcp")
    assert mcp["status"] == "ready"
    assert "<agent-token>" in mcp["command"]
    assert raw_token not in mcp["command"]

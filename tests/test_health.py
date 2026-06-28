from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from pact.api import create_app
from pact.anticheat import TokenStore
from pact.clock import FixedClock
from pact.config import load_settings
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider

_NOW = datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def client(repo):
    app = create_app(
        repo,
        TestLLMProvider(),
        TestLinkProvider(),
        TokenStore(),
        FixedClock(_NOW),
        load_settings({}),
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_health_ok(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_runtime_reports_safe_default_modes(repo):
    app = create_app(
        repo,
        TestLLMProvider(),
        TestLinkProvider(),
        TokenStore(),
        FixedClock(_NOW),
        load_settings({}),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/runtime")
        assert r.status_code == 200
        assert r.json() == {
            "payment_mode": "test_link",
            "link_mode": "dry_run",
            "reasoning_mode": "hybrid",
            "auth_mode": "local_dev",
            "live_money_enabled": False,
        }


async def test_runtime_reports_live_money_only_when_both_gates_are_live(repo):
    settings = load_settings({"PACT_PAYMENT_MODE": "link_cli", "PACT_LINK_MODE": "live"})
    app = create_app(
        repo,
        TestLLMProvider(),
        TestLinkProvider(),
        TokenStore(),
        FixedClock(_NOW),
        settings,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/runtime")
        assert r.status_code == 200
        assert r.json()["payment_mode"] == "link_cli"
        assert r.json()["link_mode"] == "live"
        assert r.json()["live_money_enabled"] is True

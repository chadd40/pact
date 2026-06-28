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
def client(repo):  # `repo` comes from tests/conftest.py
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


async def test_cors_preflight_allows_tauri_origin(client):
    r = await client.options(
        "/api/pacts/draft",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r.headers.get("access-control-allow-origin") == "tauri://localhost"


async def test_cors_blocks_unknown_origin(client):
    r = await client.options(
        "/api/pacts/draft",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r.headers.get("access-control-allow-origin") != "https://evil.example"

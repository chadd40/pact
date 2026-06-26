from datetime import datetime, timezone

import httpx
import pytest

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.charities import CHARITIES
from pact.clock import FixedClock
from pact.config import Settings
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def _build(tmp_path):
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    settings = Settings(db_path=str(tmp_path / "pact.db"))
    return create_app(repo, TestLLMProvider(), TestLinkProvider(), TokenStore(), clock, settings)


@pytest.mark.asyncio
async def test_charities_endpoint_returns_catalog(tmp_path):
    app = _build(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/charities")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body) == len(CHARITIES) == 10
        ids = {c["id"] for c in body}
        assert "world_central_kitchen" in ids
        # Each entry carries the keys the Confirm picker renders.
        for c in body:
            assert {"id", "name", "donation_url", "category", "default_amounts"} <= set(c)

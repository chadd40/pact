from datetime import datetime

import httpx
import pytest

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock, RealClock
from pact.config import Settings
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


SEED_ISO = "2026-06-22T09:00:00+00:00"


def _demo_settings(tmp_path) -> Settings:
    return Settings(
        db_path=str(tmp_path / "pact.db"),
        clock_mode="demo",
        demo_seed_iso=SEED_ISO,
    )


def _build(tmp_path, clock, settings):
    repo = Repository.connect(settings.db_path)
    repo.init_schema()
    provider = TestLLMProvider()
    payment = TestLinkProvider()
    tokens = TokenStore(ttl_minutes=10)
    app = create_app(repo, provider, payment, tokens, clock, settings)
    return app, repo


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_demo_seed_returns_three_ids(tmp_path):
    clock = FixedClock(datetime.fromisoformat(SEED_ISO))
    settings = _demo_settings(tmp_path)
    app, repo = _build(tmp_path, clock, settings)
    async with _client(app) as client:
        r = await client.post("/demo/seed")
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body.keys()) == {"win", "fail", "live"}
        # All three ids are real, distinct, persisted pacts.
        ids = {body["win"], body["fail"], body["live"]}
        assert len(ids) == 3
        for pact_id in ids:
            assert repo.get_pact(pact_id) is not None
        # WIN settled to a success with no money moved; LIVE still active.
        assert repo.get_pact(body["win"]).status == "succeeded"
        assert repo.get_pact(body["live"]).status == "active"


@pytest.mark.asyncio
async def test_demo_advance_day_advances_clock_and_settles(tmp_path):
    clock = FixedClock(datetime.fromisoformat(SEED_ISO))
    settings = _demo_settings(tmp_path)
    app, repo = _build(tmp_path, clock, settings)
    async with _client(app) as client:
        seed = (await client.post("/demo/seed")).json()
        before = clock.now()

        r = await client.post("/demo/advance-day")
        assert r.status_code == 200, r.text
        body = r.json()
        # Clock moved forward exactly 24h and the endpoint reports it.
        assert (clock.now() - before).total_seconds() == 24 * 3600
        assert datetime.fromisoformat(body["now"]) == clock.now()
        assert isinstance(body["settled"], list)

        # Keep advancing until the LIVE pact's deadline passes; it must settle.
        live_id = seed["live"]
        for _ in range(10):
            if repo.get_pact(live_id).status != "active":
                break
            await client.post("/demo/advance-day")
        assert repo.get_pact(live_id).status != "active"


@pytest.mark.asyncio
async def test_demo_reset_restores_known_state(tmp_path):
    clock = FixedClock(datetime.fromisoformat(SEED_ISO))
    settings = _demo_settings(tmp_path)
    app, repo = _build(tmp_path, clock, settings)
    async with _client(app) as client:
        first = (await client.post("/demo/seed")).json()
        # Drift the clock forward, then reset.
        await client.post("/demo/advance-day")
        await client.post("/demo/advance-day")
        assert clock.now() != datetime.fromisoformat(SEED_ISO)

        r = await client.post("/demo/reset")
        assert r.status_code == 200, r.text
        again = r.json()
        # Same stable ids and the clock is pinned back to the seed instant.
        assert again == first
        assert clock.now() == datetime.fromisoformat(SEED_ISO)
        assert repo.get_pact(again["win"]).status == "succeeded"
        assert repo.get_pact(again["live"]).status == "active"


@pytest.mark.asyncio
async def test_advance_and_reset_require_fixed_clock(tmp_path):
    clock = RealClock()
    # clock_mode left at default "real"; RealClock cannot be advanced/reset.
    settings = Settings(db_path=str(tmp_path / "pact.db"))
    app, _ = _build(tmp_path, clock, settings)
    async with _client(app) as client:
        assert (await client.post("/demo/advance-day")).status_code == 409
        assert (await client.post("/demo/reset")).status_code == 409

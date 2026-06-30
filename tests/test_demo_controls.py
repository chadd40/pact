"""Demo controls: clock_mode flag + advance-by-N, so the real app can drive the real
lifecycle fast on stage (scripted demo on the real rails)."""
import httpx
import pytest
from datetime import datetime, timezone

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock
from pact.config import Settings
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def _app(tmp_path):
    repo = Repository.connect(str(tmp_path / "p.db"))
    repo.init_schema()
    settings = Settings(db_path=str(tmp_path / "p.db"))
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    return create_app(repo, TestLLMProvider(), TestLinkProvider(), TokenStore(), clock, settings)


def _c(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_runtime_reports_clock_mode_demo(tmp_path):
    async with _c(_app(tmp_path)) as c:
        r = await c.get("/api/runtime")
        assert r.status_code == 200, r.text
        assert r.json()["clock_mode"] == "demo"  # FixedClock -> demo; the UI shows demo controls


@pytest.mark.asyncio
async def test_advance_day_accepts_days_delta(tmp_path):
    async with _c(_app(tmp_path)) as c:
        r = await c.post("/demo/advance-day", json={"days": 5})
        assert r.status_code == 200, r.text
        assert r.json()["now"].startswith("2026-06-29T12:00")  # start + 5 days


@pytest.mark.asyncio
async def test_advance_day_default_is_one_day(tmp_path):
    async with _c(_app(tmp_path)) as c:
        r = await c.post("/demo/advance-day", json={})
        assert r.json()["now"].startswith("2026-06-25T12:00")  # +24h default

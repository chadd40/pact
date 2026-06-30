"""T1: billing profile captured at onboarding (name + address) for charity-form filling."""
import httpx
import pytest
from datetime import datetime, timezone

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock
from pact.config import Settings
from pact.models import Profile
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def _build(tmp_path):
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    settings = Settings(db_path=str(tmp_path / "pact.db"), artifacts_dir=str(tmp_path / "artifacts"))
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app = create_app(repo, TestLLMProvider(), TestLinkProvider(), TokenStore(), clock, settings)
    return app, repo


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_billing_set_and_get_round_trip(tmp_path):
    app, _ = _build(tmp_path)
    async with _client(app) as c:
        body = {
            "owner": "demo@pact.local", "first_name": "Ada", "last_name": "Lovelace",
            "email": "ada@example.com", "street": "1 Analytical Way", "city": "London",
            "state": "", "postal_code": "EC1A 1AA", "country": "GB",
        }
        r = await c.post("/api/account/billing", json=body)
        assert r.status_code == 200, r.text
        r = await c.get("/api/account/billing", params={"owner": "demo@pact.local"})
        assert r.status_code == 200, r.text
        got = r.json()
        assert got["first_name"] == "Ada" and got["last_name"] == "Lovelace"
        assert got["street"] == "1 Analytical Way" and got["postal_code"] == "EC1A 1AA"
        assert got["country"] == "GB" and got["email"] == "ada@example.com"


@pytest.mark.asyncio
async def test_billing_preserves_other_profile_fields(tmp_path):
    app, repo = _build(tmp_path)
    async with _client(app) as c:
        repo.save_profile(Profile(owner="demo@pact.local", current_streak=3, spend_limit_cents=5000))
        r = await c.post("/api/account/billing", json={"owner": "demo@pact.local", "first_name": "Ada"})
        assert r.status_code == 200, r.text
        prof = repo.get_profile("demo@pact.local")
        assert prof.current_streak == 3 and prof.spend_limit_cents == 5000  # preserved
        assert prof.first_name == "Ada"

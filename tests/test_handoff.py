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

OWNER = "colehaddad40@gmail.com"


def _build(tmp_path):
    db = str(tmp_path / "p.db")
    repo = Repository.connect(db)
    repo.init_schema()
    clock = FixedClock(datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc))
    app = create_app(repo, TestLLMProvider(), TestLinkProvider(), TokenStore(), clock, Settings(db_path=db))
    return app


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_create_flow_seeds_agent_handoff(tmp_path):
    """The primary (structured Create) path: sealing a pact greets the owner."""
    app = _build(tmp_path)
    async with _client(app) as client:
        r = await client.post(
            "/api/pacts/create",
            json={
                "goal_title": "Work out",
                "days_per_week": 5,
                "weeks": 4,
                "stake_amount_cents": 20000,
                "charity_id": "against_malaria_foundation",
                "agent": "Hermes",
                "consent_acknowledged": True,
                "owner": OWNER,
            },
        )
        assert r.status_code == 200, r.text
        pact_id = r.json()["id"]

        thread = (await client.get(f"/api/pacts/{pact_id}/coach")).json()
        handoffs = [m for m in thread if m["trigger"] == "handoff"]
        assert len(handoffs) == 1
        assert handoffs[0]["direction"] == "outbound"
        assert handoffs[0]["body"]

        # Also queued in the agent's outbox (undelivered) for relay in-channel.
        outbox = (await client.get("/api/outbox", params={"owner": OWNER})).json()
        assert any(m["id"] == handoffs[0]["id"] for m in outbox)


@pytest.mark.asyncio
async def test_confirm_flow_seeds_single_handoff(tmp_path):
    """The legacy draft→confirm path also greets, exactly once (start is a no-op)."""
    app = _build(tmp_path)
    async with _client(app) as client:
        r = await client.post(
            "/api/pacts/draft",
            json={"prompt": "do a thing 5x this week or $15 to charity"},
        )
        pact_id = r.json()["id"]
        await client.post(
            "/api/pacts",
            json={
                "pact_id": pact_id,
                "stake_amount_cents": 1500,
                "charity_id": "against_malaria_foundation",
                "consent_acknowledged": True,
            },
        )
        await client.post(f"/api/pacts/{pact_id}/owner", json={"owner": OWNER})
        await client.post(f"/api/pacts/{pact_id}/start")  # already active: no 2nd handoff

        thread = (await client.get(f"/api/pacts/{pact_id}/coach")).json()
        assert len([m for m in thread if m["trigger"] == "handoff"]) == 1

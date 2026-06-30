"""Task 8: end-to-end agent last-mile donation in dry-run/test (no real money).

Drives the full reordered lifecycle through the API:
  draft -> create (pre-authorized: spend-request + card escrowed, active)
        -> fail -> settle (24h window) -> window closes -> donation_pending (owed)
        -> agent obtains the chargeable card -> resolve (Link-confirmed) -> donation_complete
"""
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


def _build(tmp_path):
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    settings = Settings(db_path=str(tmp_path / "pact.db"), artifacts_dir=str(tmp_path / "artifacts"))
    tokens = TokenStore(ttl_minutes=10)
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app = create_app(repo, TestLLMProvider(), TestLinkProvider(), tokens, clock, settings)
    return app, repo, clock


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _create(client, prompt="do a thing 5x this week or $15 to charity"):
    r = await client.post("/api/pacts/draft", json={"prompt": prompt})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = await client.post("/api/pacts", json={
        "pact_id": pid, "stake_amount_cents": 1500,
        "charity_id": "against_malaria_foundation", "consent_acknowledged": True,
    })
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/pacts/{pid}/start")
    assert r.status_code == 200, r.text
    return pid


@pytest.mark.asyncio
async def test_agent_last_mile_dryrun_end_to_end(tmp_path):
    app, repo, clock = _build(tmp_path)
    async with _client(app) as client:
        pid = await _create(client)

        # Pre-authorized at creation: spend-request + single-use card escrowed, active.
        created = repo.get_pact(pid)
        assert created.status == "active"
        assert created.spend_request_id == f"test_sr_{pid}_1500"
        assert created.card_last4 == "4242"

        # Owner + connected Link so the deferred donation is allowed to fire.
        p = repo.get_pact(pid)
        p.owner = "demo@pact.local"
        repo.update_pact(p)
        await client.post("/api/link/connect", json={"owner": "demo@pact.local"})

        # Fail: never reach the target; advance past the deadline, then settle.
        clock.advance(days=40)
        r = await client.post(f"/api/pacts/{pid}/settle")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "failed"

        # Inside the window: still failed, no charge. Past the window: OWED.
        clock.advance(days=2)  # > 24h dispute grace
        r = await client.post(f"/api/pacts/{pid}/settle")
        assert r.status_code == 200, r.text
        owed = repo.get_pact(pid)
        assert owed.status == "donation_pending"            # ready for the agent to pay
        assert owed.spend_request_id == f"test_sr_{pid}_1500"  # reused, not re-created

        # Gate opens: the agent can now obtain the chargeable single-use card.
        cred = await client.post(f"/api/pacts/{pid}/donation/card-credential")
        assert cred.status_code == 200, cred.text
        assert cred.json()["number"]  # full PAN released to the owner's agent

        # The agent paid the charity with that card. Resolve confirms via Link.
        res = await client.post(f"/api/pacts/{pid}/donation/resolve")
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "donation_complete"
        assert res.json()["confirmed"] is True

        final = repo.get_pact(pid)
        assert final.status == "donation_complete"          # terminal, resolved
        receipt = await client.get(f"/api/pacts/{pid}/donation/receipt")
        assert receipt.status_code == 200, receipt.text
        assert receipt.json()["receipt_status"] == "provider_confirmed"
        assert receipt.json()["receipt_source"] == "link"
        assert receipt.json()["receipt_ref"] == f"test_sr_{pid}_1500"

        # Idempotent: re-resolving a completed pact is a no-op confirm.
        res2 = await client.post(f"/api/pacts/{pid}/donation/resolve")
        assert res2.status_code == 200, res2.text
        assert repo.get_pact(pid).status == "donation_complete"

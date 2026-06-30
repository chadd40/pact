"""Task 3: API creation pre-authorizes the stake; /stake/confirm picks up the card."""
import httpx
import pytest
from datetime import datetime, timezone

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock
from pact.config import Settings
from pact.payment import CardCredential, PaymentResult, TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def _build(tmp_path, payment):
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    settings = Settings(db_path=str(tmp_path / "pact.db"), artifacts_dir=str(tmp_path / "artifacts"))
    tokens = TokenStore(ttl_minutes=10)
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    return create_app(repo, TestLLMProvider(), payment, tokens, clock, settings), repo


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _draft_id(client, prompt="do a thing 5x this week or $15 to charity"):
    r = await client.post("/api/pacts/draft", json={"prompt": prompt})
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _create(client, pid, cents=1500):
    return await client.post("/api/pacts", json={
        "pact_id": pid, "stake_amount_cents": cents,
        "charity_id": "against_malaria_foundation", "consent_acknowledged": True,
    })


class _PendingProvider:
    provider = "link_cli"

    def __init__(self):
        self.approved = False

    def create_donation(self, pact, idempotency_key):
        return PaymentResult(
            provider="link_cli", status="pending_approval", provider_ref="lsrq_p",
            payload={"link_cli": {"approval_url": "https://link/approve/abc"}},
        )

    def retrieve_card(self, provider_ref, *, output_dir):
        if not self.approved:
            raise RuntimeError("link-cli returned no card; not approved yet")
        return CardCredential(
            provider="link_cli", spend_request_id=provider_ref,
            card_file=f"{output_dir}/card_{provider_ref}.json", last4="8855", brand="visa",
            exp_month=8, exp_year=2028, mode="live",
        )


@pytest.mark.asyncio
async def test_create_dryrun_activates_with_card(tmp_path):
    app, _ = _build(tmp_path, TestLinkProvider())
    async with _client(app) as client:
        pid = await _draft_id(client)
        r = await _create(client, pid)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "active"
        assert body["card_last4"]  # provisioned at creation
        assert body["spend_request_id"]


@pytest.mark.asyncio
async def test_create_live_pending_awaits_then_stake_confirm(tmp_path):
    prov = _PendingProvider()
    app, _ = _build(tmp_path, prov)
    async with _client(app) as client:
        pid = await _draft_id(client)
        r = await _create(client, pid)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "awaiting_stake"
        assert body["stake_approval_url"] == "https://link/approve/abc"
        assert body["card_last4"] is None

        prov.approved = True  # human approved in Link
        r = await client.post(f"/api/pacts/{pid}/stake/confirm")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "active"
        assert r.json()["card_last4"] == "8855"


@pytest.mark.asyncio
async def test_card_credential_blocked_until_payable(tmp_path):
    # The chargeable card is released only once the pact is failed + window elapsed
    # (donation_pending/donated). While active, the agent must not be able to pull it.
    app, _ = _build(tmp_path, TestLinkProvider())
    async with _client(app) as client:
        pid = await _draft_id(client)
        await _create(client, pid)  # active, card provisioned
        r = await client.post(f"/api/pacts/{pid}/donation/card-credential")
        assert r.status_code == 409, r.text

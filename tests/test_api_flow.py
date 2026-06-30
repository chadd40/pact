from datetime import datetime, timezone

import httpx
import pytest

from pact.api import create_app
from pact.anticheat import TokenStore
from pact.clock import FixedClock
from pact.config import Settings
from pact.models import PactStatus, StakeState
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def _build(tmp_path, clock):
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    provider = TestLLMProvider()
    payment = TestLinkProvider()
    tokens = TokenStore(ttl_minutes=10)
    settings = Settings(db_path=str(tmp_path / "pact.db"))
    app = create_app(repo, provider, payment, tokens, clock, settings)
    return app, repo


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _draft_confirm_start(client, prompt):
    r = await client.post("/api/pacts/draft", json={"prompt": prompt})
    assert r.status_code == 200, r.text
    pact_id = r.json()["id"]
    assert pact_id.startswith("pact_")

    r = await client.post(
        "/api/pacts",
        json={
            "pact_id": pact_id,
            "stake_amount_cents": 1500,
            "charity_id": "against_malaria_foundation",
            "consent_acknowledged": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["charity_id"] == "against_malaria_foundation"

    r = await client.post(f"/api/pacts/{pact_id}/start")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"
    return pact_id


async def _submit_valid_proof(client, pact_id):
    r = await client.post(f"/api/pacts/{pact_id}/proof-token")
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    r = await client.post(
        f"/api/pacts/{pact_id}/proofs",
        json={
            "modality": "text",
            "token": token,
            "content_ok": True,
            "image_path": None,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_win_flow_succeeds_with_no_donation(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(client, "do a thing 5x this week or $15 to charity")

        for _ in range(5):
            proof = await _submit_valid_proof(client, pact_id)
            assert proof["status"] == "passed"
            clock.advance(days=1)

        r = await client.post(f"/api/pacts/{pact_id}/settle")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "succeeded"
        assert body["payment_action"] == "none"
        assert body["payment_ref"] is None

        r = await client.get(f"/api/pacts/{pact_id}/packet")
        assert r.status_code == 200, r.text
        packet = r.json()
        assert packet["verdict"]["status"] == "succeeded"
        assert packet["verdict"]["payment_action"] == "none"
        assert packet["verdict"]["valid_proof_count"] == 5

        # Pre-authorized at creation but never charged on success: the spend-request
        # id remains (escrow that expires unused), the stake is released, no money moved.
        r = await client.get(f"/api/pacts/{pact_id}")
        assert r.json()["spend_request_id"] == f"test_sr_{pact_id}_1500"
        assert r.json()["stake_state"] == "released"
        assert r.json()["card_last4"] == "4242"  # provisioned upfront, never used


@pytest.mark.asyncio
async def test_fail_flow_defers_then_owes_after_window(tmp_path):
    # New model: the spend-request + card are pre-authorized at CREATION. On fail,
    # after the 24h window the pact OWES the donation (donation_pending) -- it does
    # NOT auto-charge here; the agent pays the charity with the pre-approved card
    # (covered end-to-end in test_agent_last_mile_e2e). No new spend-request is created.
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, repo = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(client, "do a thing 5x this week or $15 to charity")

        # Pre-authorized at creation: spend-request + card already exist.
        created = repo.get_pact(pact_id)
        assert created.spend_request_id == f"test_sr_{pact_id}_1500"
        assert created.card_last4 == "4242"

        p0 = repo.get_pact(pact_id)
        p0.owner = "demo@pact.local"
        repo.update_pact(p0)
        await client.post("/api/link/connect", json={"owner": "demo@pact.local"})

        for _ in range(4):
            await _submit_valid_proof(client, pact_id)
            clock.advance(days=1)
        clock.advance(days=30)  # past the deadline

        # Phase 1: settle FAILS, defers behind the dispute window. No charge.
        r = await client.post(f"/api/pacts/{pact_id}/settle")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "failed"
        assert body["payment_action"] == "none"

        pact = repo.get_pact(pact_id)
        assert pact.status == "failed"
        assert pact.spend_request_id == f"test_sr_{pact_id}_1500"  # the pre-auth ref, unchanged
        assert pact.stake_state == "committed"
        assert pact.dispute_window_closes_at is not None

        # Phase 2: past the window, settle closes it -> the donation is OWED, ready for
        # the agent to pay. No money moves here; the pre-auth ref is reused (not re-created).
        clock.advance(days=2)  # > 24h default grace
        r = await client.post(f"/api/pacts/{pact_id}/settle")
        assert r.status_code == 200, r.text
        assert r.json()["payment_action"] == "none"

        owed = repo.get_pact(pact_id)
        assert owed.status == "donation_pending"  # ready for the agent to pay
        assert owed.spend_request_id == f"test_sr_{pact_id}_1500"  # reused, not re-created
        assert owed.stake_state == "committed"
        # No Pact-side charge attempt: the agent charges the card at the charity.
        assert repo.list_payment_attempts(pact_id) == []


@pytest.mark.asyncio
async def test_receipt_cannot_be_recorded_before_donation(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(client, "do a thing 5x this week or $15 to charity")

        receipt = await client.post(
            f"/api/pacts/{pact_id}/donation/receipt",
            json={"receipt_status": "manual_receipt", "receipt_ref": "TOO-EARLY"},
        )
        assert receipt.status_code == 409

        confirmed = await client.post(f"/api/pacts/{pact_id}/donation/confirm")
        assert confirmed.status_code == 409


@pytest.mark.asyncio
async def test_receipt_rejects_unknown_confirmation_status(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, repo = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(client, "do a thing 5x this week or $15 to charity")
        pact = repo.get_pact(pact_id)
        repo.update_pact(
            pact.model_copy(
                update={
                    "status": PactStatus.donated,
                    "stake_state": StakeState.executed,
                    "spend_request_id": "sr_test_receipt",
                }
            )
        )

        receipt = await client.post(
            f"/api/pacts/{pact_id}/donation/receipt",
            json={"receipt_status": "definitely_confirmed", "receipt_ref": "BAD"},
        )
        assert receipt.status_code == 422

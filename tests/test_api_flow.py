from datetime import datetime, timezone

import httpx
import pytest

from pact.api import create_app
from pact.anticheat import TokenStore
from pact.clock import FixedClock
from pact.config import Settings
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
            "charity_id": "world_central_kitchen",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["charity_id"] == "world_central_kitchen"

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

        # No spend-request on success: the pact never recorded one.
        r = await client.get(f"/api/pacts/{pact_id}")
        assert r.json()["spend_request_id"] is None
        assert r.json()["stake_state"] == "released"


@pytest.mark.asyncio
async def test_fail_flow_defers_then_donates_after_window(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, repo = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(client, "do a thing 5x this week or $15 to charity")

        for _ in range(4):
            await _submit_valid_proof(client, pact_id)
            clock.advance(days=1)

        # Advance well past the deadline so the pact is due.
        clock.advance(days=30)

        # Phase 1: settle FAILS but defers the donation behind the dispute window.
        r = await client.post(f"/api/pacts/{pact_id}/settle")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "failed"
        assert body["valid_proof_count"] == 4
        assert body["target_count"] == 5
        assert body["payment_action"] == "none"
        assert body["payment_ref"] is None

        pact = repo.get_pact(pact_id)
        assert pact.status == "failed"
        assert pact.spend_request_id is None
        assert pact.stake_state == "committed"
        assert pact.dispute_window_closes_at is not None

        # Re-settling inside the open window is a no-op: still failed, still no money.
        r_again = await client.post(f"/api/pacts/{pact_id}/settle")
        assert r_again.status_code == 200, r_again.text
        assert r_again.json()["payment_action"] == "none"
        assert repo.get_pact(pact_id).spend_request_id is None

        # Phase 2: advance past the grace window, then settle closes the window and
        # executes the deferred donation exactly once.
        clock.advance(days=2)  # > 24h default grace
        r = await client.post(f"/api/pacts/{pact_id}/settle")
        assert r.status_code == 200, r.text
        body2 = r.json()
        assert body2["payment_action"] == "donation_executed"
        assert body2["payment_ref"] == f"test_sr_{pact_id}_1500"

        donated = repo.get_pact(pact_id)
        assert donated.status == "donated"
        assert donated.spend_request_id == f"test_sr_{pact_id}_1500"
        assert donated.stake_state == "executed"

        # Idempotent: a second settle after donation moves no additional money.
        r2 = await client.post(f"/api/pacts/{pact_id}/settle")
        assert r2.status_code == 200, r2.text
        assert r2.json()["payment_ref"] == f"test_sr_{pact_id}_1500"
        assert repo.get_pact(pact_id).spend_request_id == f"test_sr_{pact_id}_1500"

        r = await client.get(f"/api/pacts/{pact_id}/packet")
        assert r.json()["verdict"]["payment_action"] == "donation_executed"
        assert r.json()["verdict"]["payment_ref"] == f"test_sr_{pact_id}_1500"

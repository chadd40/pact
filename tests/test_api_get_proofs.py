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

    r = await client.post(
        "/api/pacts",
        json={
            "pact_id": pact_id,
            "stake_amount_cents": 1500,
            "charity_id": "world_central_kitchen",
        },
    )
    assert r.status_code == 200, r.text

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
async def test_get_proofs_returns_two_in_order(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(
            client, "do a thing 5x this week or $15 to charity"
        )

        first = await _submit_valid_proof(client, pact_id)
        clock.advance(days=1)
        second = await _submit_valid_proof(client, pact_id)

        r = await client.get(f"/api/pacts/{pact_id}/proofs")
        assert r.status_code == 200, r.text
        proofs = r.json()
        assert isinstance(proofs, list)
        assert len(proofs) == 2

        # Ordered by received_at ascending: the first-submitted proof comes first.
        assert proofs[0]["id"] == first["id"]
        assert proofs[1]["id"] == second["id"]
        received = [p["received_at"] for p in proofs]
        assert received == sorted(received)

        # Server-truth fields the UI relies on.
        for p in proofs:
            assert p["pact_id"] == pact_id
            assert p["status"] == "passed"
        # Distinct days because the clock advanced one day between submissions.
        assert proofs[0]["day_bucket"] != proofs[1]["day_bucket"]


@pytest.mark.asyncio
async def test_get_proofs_empty_for_fresh_pact(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(
            client, "do a thing 5x this week or $15 to charity"
        )
        r = await client.get(f"/api/pacts/{pact_id}/proofs")
        assert r.status_code == 200, r.text
        assert r.json() == []


@pytest.mark.asyncio
async def test_get_proofs_404_for_missing_pact(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        r = await client.get("/api/pacts/pact_missing/proofs")
        assert r.status_code == 404, r.text
        assert r.json()["detail"] == "pact not found"

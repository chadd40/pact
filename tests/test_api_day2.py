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
    db = str(tmp_path / "pact.db")
    repo = Repository.connect(db)
    repo.init_schema()
    provider = TestLLMProvider()
    payment = TestLinkProvider()
    tokens = TokenStore(ttl_minutes=10)
    settings = Settings(db_path=db)
    app = create_app(repo, provider, payment, tokens, clock, settings)
    return app, repo


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _draft_confirm_start(client, prompt, owner="demo@pact.local"):
    r = await client.post("/api/pacts/draft", json={"prompt": prompt})
    assert r.status_code == 200, r.text
    pact_id = r.json()["id"]

    r = await client.post(
        "/api/pacts",
        json={
            "pact_id": pact_id,
            "stake_amount_cents": 1500,
            "charity_id": "world_central_kitchen",
            "consent_acknowledged": True,
        },
    )
    assert r.status_code == 200, r.text

    # Stamp the owner so the profile has a stable key to aggregate under.
    r = await client.post(f"/api/pacts/{pact_id}/owner", json={"owner": owner})
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
        json={"modality": "text", "token": token, "content_ok": True, "image_path": None},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_profile_reflects_a_win_after_settle(tmp_path):
    owner = "demo@pact.local"
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        # Unknown owner returns a default empty profile (created on read).
        r = await client.get("/api/profile", params={"owner": owner})
        assert r.status_code == 200, r.text
        blank = r.json()
        assert blank["owner"] == owner
        assert blank["kept"] == 0
        assert blank["current_streak"] == 0
        assert blank["history"] == []

        pact_id = await _draft_confirm_start(client, "do a thing 5x this week or $15 to charity", owner)
        for _ in range(5):
            assert (await _submit_valid_proof(client, pact_id))["status"] == "passed"
            clock.advance(days=1)

        r = await client.post(f"/api/pacts/{pact_id}/settle")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "succeeded"

        r = await client.get("/api/profile", params={"owner": owner})
        assert r.status_code == 200, r.text
        prof = r.json()
        assert prof["owner"] == owner
        assert prof["kept"] == 1
        assert prof["failed"] == 0
        assert prof["current_streak"] == 1
        assert prof["best_streak"] == 1
        assert pact_id in prof["pact_ids"]
        assert len(prof["history"]) == 1
        assert prof["history"][0]["pact_id"] == pact_id
        assert prof["history"][0]["outcome"] == "succeeded"


@pytest.mark.asyncio
async def test_coach_post_returns_inbound_and_outbound_and_get_shows_thread(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(client, "do a thing 5x this week or $15 to charity")

        # Empty thread to start.
        r = await client.get(f"/api/pacts/{pact_id}/coach")
        assert r.status_code == 200, r.text
        assert r.json() == []

        r = await client.post(
            f"/api/pacts/{pact_id}/coach",
            json={"message": "I did two sessions today, on track?"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["inbound"]["direction"] == "inbound"
        assert body["inbound"]["trigger"] == "reply"
        assert body["inbound"]["body"] == "I did two sessions today, on track?"
        assert body["inbound"]["pact_id"] == pact_id
        assert body["outbound"]["direction"] == "outbound"
        assert body["outbound"]["trigger"] == "reply"
        assert body["outbound"]["body"]

        r = await client.get(f"/api/pacts/{pact_id}/coach")
        assert r.status_code == 200, r.text
        thread = r.json()
        assert len(thread) == 2
        assert thread[0]["direction"] == "inbound"
        assert thread[1]["direction"] == "outbound"
        assert {m["id"] for m in thread} == {body["inbound"]["id"], body["outbound"]["id"]}


@pytest.mark.asyncio
async def test_coach_log_appears_in_packet(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(client, "do a thing 5x this week or $15 to charity")
        await client.post(f"/api/pacts/{pact_id}/coach", json={"message": "checking in"})

        for _ in range(5):
            await _submit_valid_proof(client, pact_id)
            clock.advance(days=1)
        r = await client.post(f"/api/pacts/{pact_id}/settle")
        assert r.status_code == 200, r.text

        r = await client.get(f"/api/pacts/{pact_id}/packet")
        assert r.status_code == 200, r.text
        packet = r.json()
        assert "coaching_log" in packet
        assert len(packet["coaching_log"]) == 2
        assert packet["coaching_log"][0]["direction"] == "inbound"
        assert packet["coaching_log"][1]["direction"] == "outbound"


@pytest.mark.asyncio
async def test_renew_finished_pact_yields_new_draft_with_copied_terms(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(client, "do a thing 5x this week or $15 to charity")
        for _ in range(5):
            await _submit_valid_proof(client, pact_id)
            clock.advance(days=1)
        r = await client.post(f"/api/pacts/{pact_id}/settle")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "succeeded"

        orig = (await client.get(f"/api/pacts/{pact_id}")).json()

        r = await client.post(f"/api/pacts/{pact_id}/renew")
        assert r.status_code == 200, r.text
        fresh = r.json()
        assert fresh["id"] != pact_id
        assert fresh["id"].startswith("pact_")
        assert fresh["status"] == "draft"
        assert fresh["goal"] == orig["goal"]
        assert fresh["title"] == orig["title"]
        assert fresh["target_count"] == orig["target_count"]
        assert fresh["rubric"] == orig["rubric"]
        # Fresh draft: terms left to confirm, no money state carried over.
        assert fresh["stake_state"] == "none"
        assert fresh["spend_request_id"] is None

        # The new draft is persisted and fetchable.
        r = await client.get(f"/api/pacts/{fresh['id']}")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "draft"

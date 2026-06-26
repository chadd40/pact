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


async def _draft_pact(client, prompt):
    r = await client.post("/api/pacts/draft", json={"prompt": prompt})
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_enqueue_appears_in_pending_then_claim_result_roundtrip(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_pact(client, "do a thing 5x this week or $15 to charity")

        # Enqueue a judge_proof task for this pact, scoped to the "vision" capability.
        r = await client.post(
            f"/api/pacts/{pact_id}/reasoning-tasks",
            json={
                "type": "judge_proof",
                "input": {"token_ok": True, "is_duplicate": False, "content_ok": True},
                "required_capability": "vision",
            },
        )
        assert r.status_code == 200, r.text
        task = r.json()
        tid = task["id"]
        assert tid.startswith("task_")
        assert task["pact_id"] == pact_id
        assert task["type"] == "judge_proof"
        assert task["required_capability"] == "vision"
        assert task["status"] == "pending"
        assert task["result"] is None

        # It shows up in the pending list, filtered by capability.
        r = await client.get("/api/reasoning-tasks", params={"capability": "vision"})
        assert r.status_code == 200, r.text
        ids = [t["id"] for t in r.json()]
        assert tid in ids

        # An unrelated capability filter excludes it.
        r = await client.get("/api/reasoning-tasks", params={"capability": "audio"})
        assert r.status_code == 200, r.text
        assert tid not in [t["id"] for t in r.json()]

        # Claim it with a matching capability set.
        r = await client.post(
            f"/api/reasoning-tasks/{tid}/claim",
            json={"agent_name": "worker-1", "capabilities": ["text", "vision"]},
        )
        assert r.status_code == 200, r.text
        claimed = r.json()
        assert claimed["status"] == "claimed"
        assert claimed["claimed_by"] == "worker-1"

        # Once claimed it is no longer pending.
        r = await client.get("/api/reasoning-tasks", params={"status": "pending"})
        assert r.status_code == 200, r.text
        assert tid not in [t["id"] for t in r.json()]

        # Post a result back; the task flips to done and carries the payload.
        r = await client.post(
            f"/api/reasoning-tasks/{tid}/result",
            json={"result": {"status": "passed", "reason": "looks good"}},
        )
        assert r.status_code == 200, r.text
        done = r.json()
        assert done["status"] == "done"
        assert done["result"] == {"status": "passed", "reason": "looks good"}


@pytest.mark.asyncio
async def test_claim_capability_mismatch_returns_409(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_pact(client, "do a thing 5x this week or $15 to charity")

        r = await client.post(
            f"/api/pacts/{pact_id}/reasoning-tasks",
            json={
                "type": "judge_proof",
                "input": {"token_ok": True, "is_duplicate": False, "content_ok": True},
                "required_capability": "vision",
            },
        )
        assert r.status_code == 200, r.text
        tid = r.json()["id"]

        # Worker lacks the required "vision" capability.
        r = await client.post(
            f"/api/reasoning-tasks/{tid}/claim",
            json={"agent_name": "blind-worker", "capabilities": ["text"]},
        )
        assert r.status_code == 409, r.text

        # The task remains pending and unclaimed.
        r = await client.get("/api/reasoning-tasks", params={"status": "pending"})
        assert tid in [t["id"] for t in r.json()]


@pytest.mark.asyncio
async def test_post_result_to_unclaimed_task_returns_409(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_pact(client, "do a thing 5x this week or $15 to charity")

        r = await client.post(
            f"/api/pacts/{pact_id}/reasoning-tasks",
            json={
                "type": "coach",
                "input": {"valid": 1, "target": 5, "days_left": 3, "charity": "WCK"},
            },
        )
        assert r.status_code == 200, r.text
        tid = r.json()["id"]

        # No claim happened, so posting a result is a 409.
        r = await client.post(
            f"/api/reasoning-tasks/{tid}/result",
            json={"result": {"message": "keep going"}},
        )
        assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_claim_missing_task_returns_409(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        r = await client.post(
            "/api/reasoning-tasks/task_does_not_exist/claim",
            json={"agent_name": "worker-1", "capabilities": ["text", "vision"]},
        )
        assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_no_capability_filter_lists_all_pending(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_pact(client, "do a thing 5x this week or $15 to charity")

        # One capability-scoped task and one unscoped task.
        r = await client.post(
            f"/api/pacts/{pact_id}/reasoning-tasks",
            json={"type": "verdict", "input": {"valid": 5, "target": 5},
                  "required_capability": "text"},
        )
        assert r.status_code == 200, r.text
        scoped = r.json()["id"]

        r = await client.post(
            f"/api/pacts/{pact_id}/reasoning-tasks",
            json={"type": "verdict", "input": {"valid": 4, "target": 5}},
        )
        assert r.status_code == 200, r.text
        unscoped = r.json()["id"]

        r = await client.get("/api/reasoning-tasks")
        assert r.status_code == 200, r.text
        ids = [t["id"] for t in r.json()]
        assert scoped in ids
        assert unscoped in ids

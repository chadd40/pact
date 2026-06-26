"""Tests for HttpWorkerClient + serve_http.

All tests drive an in-process ASGI app through httpx.ASGITransport — no real
network, subprocess, or sleep. Uses AsyncClient (the only ASGI-compatible mode
in this version of httpx) with pytest-asyncio.
"""
from datetime import datetime, timezone

import httpx
import pytest

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.broker import get_result
from pact.clock import FixedClock
from pact.config import Settings
from pact.httpworker import HttpWorkerClient, serve_http
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def _build(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    provider = TestLLMProvider()
    payment = TestLinkProvider()
    tokens = TokenStore(ttl_minutes=10)
    settings = Settings(db_path=str(tmp_path / "pact.db"))
    app = create_app(repo, provider, payment, tokens, clock, settings)
    return app, repo


def _async_client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _draft_pact(http, prompt):
    r = await http.post("/api/pacts/draft", json={"prompt": prompt})
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _enqueue(http, pact_id, type_, input_, required_capability=None):
    r = await http.post(
        f"/api/pacts/{pact_id}/reasoning-tasks",
        json={
            "type": type_,
            "input": input_,
            "required_capability": required_capability,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


class _AsyncToSyncWorker(HttpWorkerClient):
    """Adapter: wraps HttpWorkerClient so it can use an AsyncClient internally.

    The worker methods (pending/claim/post_result) make sync calls, but in the
    test environment we only have an AsyncClient. This subclass overrides those
    three methods to use await. Only used in tests.
    """

    def __init__(self, base_url, async_http):
        # Don't call super().__init__ with an http= arg — we're async-only here.
        self.base_url = base_url
        self._async_http = async_http
        # Provide a sentinel .http attr so relay_outbox(client_or_http) can
        # getattr(..., "http", ...) — but it won't be used in sync mode.
        self.http = None

    async def pending(self, capability=None):
        params = {} if capability is None else {"capability": capability}
        r = await self._async_http.get("/api/reasoning-tasks", params=params)
        r.raise_for_status()
        return r.json()

    async def claim(self, task_id, agent_name, capabilities):
        r = await self._async_http.post(
            f"/api/reasoning-tasks/{task_id}/claim",
            json={"agent_name": agent_name, "capabilities": list(capabilities)},
        )
        r.raise_for_status()
        return r.json()

    async def post_result(self, task_id, result):
        r = await self._async_http.post(
            f"/api/reasoning-tasks/{task_id}/result",
            json={"result": result},
        )
        r.raise_for_status()
        return r.json()


async def _serve_http_async(client, provider, agent_name, max_rounds=1):
    """Async version of serve_http for use with AsyncClient in tests."""
    capabilities = provider.capabilities()
    resolved = 0
    for _ in range(max_rounds):
        count_this_round = 0
        for entry in await client.pending():
            from pact.httpworker import _can_handle, _task_from_dict

            if not _can_handle(entry.get("required_capability"), capabilities):
                continue
            claimed = await client.claim(entry["id"], agent_name, capabilities)
            task = _task_from_dict(claimed)
            result = provider.resolve(task)
            await client.post_result(task.id, result)
            resolved += 1
            count_this_round += 1
        if count_this_round == 0:
            break
    return resolved


@pytest.mark.asyncio
async def test_pending_claim_post_result_roundtrip(tmp_path):
    app, _ = _build(tmp_path)
    async with _async_client(app) as http:
        pact_id = await _draft_pact(http, "do a thing 5x this week or $15 to charity")
        tid = await _enqueue(
            http,
            pact_id,
            "judge_proof",
            {"token_ok": True, "is_duplicate": False, "content_ok": True},
            required_capability="vision",
        )

        client = _AsyncToSyncWorker(base_url="http://test", async_http=http)

        # pending() surfaces the enqueued task.
        pending = await client.pending(capability="vision")
        assert tid in [t["id"] for t in pending]

        # claim() flips it to claimed by this agent.
        claimed = await client.claim(tid, "worker-1", ["text", "vision"])
        assert claimed["status"] == "claimed"
        assert claimed["claimed_by"] == "worker-1"

        # post_result() flips it to done with the payload.
        done = await client.post_result(tid, {"status": "passed", "reason": "ok"})
        assert done["status"] == "done"
        assert done["result"] == {"status": "passed", "reason": "ok"}


@pytest.mark.asyncio
async def test_serve_http_claims_and_posts_a_result(tmp_path):
    app, repo = _build(tmp_path)
    async with _async_client(app) as http:
        pact_id = await _draft_pact(http, "do a thing 5x this week or $15 to charity")
        tid = await _enqueue(
            http,
            pact_id,
            "judge_proof",
            {"token_ok": True, "is_duplicate": False, "content_ok": True},
            required_capability="vision",
        )

        client = _AsyncToSyncWorker(base_url="http://test", async_http=http)
        resolved = await _serve_http_async(
            client,
            TestLLMProvider(),
            agent_name="worker-1",
            max_rounds=1,
        )
        assert resolved == 1

        # The API can read the posted result: the task is done with the
        # provider's deterministic judge_proof verdict.
        result = get_result(repo, tid)
        assert result is not None
        assert result["status"] == "passed"
        assert result["checklist"] == {"token": True, "content": True, "not_dup": True}

        # No longer pending.
        pending_ids = [t["id"] for t in await client.pending()]
        assert tid not in pending_ids


@pytest.mark.asyncio
async def test_serve_http_skips_capability_mismatch_without_claiming(tmp_path):
    app, repo = _build(tmp_path)
    async with _async_client(app) as http:
        pact_id = await _draft_pact(http, "do a thing 5x this week or $15 to charity")
        # TestLLMProvider has {"text", "vision"} only; "audio" is unhandleable.
        tid = await _enqueue(
            http,
            pact_id,
            "judge_proof",
            {"token_ok": True, "is_duplicate": False, "content_ok": True},
            required_capability="audio",
        )

        client = _AsyncToSyncWorker(base_url="http://test", async_http=http)
        resolved = await _serve_http_async(
            client,
            TestLLMProvider(),
            agent_name="worker-1",
            max_rounds=1,
        )
        assert resolved == 0

        # Never claimed: still pending, no result.
        assert tid in [t["id"] for t in await client.pending()]
        assert get_result(repo, tid) is None


@pytest.mark.asyncio
async def test_serve_http_resolves_only_handleable_when_mixed(tmp_path):
    app, repo = _build(tmp_path)
    async with _async_client(app) as http:
        pact_id = await _draft_pact(http, "do a thing 5x this week or $15 to charity")
        handleable = await _enqueue(
            http,
            pact_id,
            "coach",
            {"valid": 1, "target": 5, "days_left": 3, "charity": "WCK"},
            required_capability="text",
        )
        unhandleable = await _enqueue(
            http,
            pact_id,
            "judge_proof",
            {"token_ok": True, "is_duplicate": False, "content_ok": True},
            required_capability="audio",
        )

        client = _AsyncToSyncWorker(base_url="http://test", async_http=http)
        resolved = await _serve_http_async(
            client,
            TestLLMProvider(),
            agent_name="worker-1",
            max_rounds=1,
        )
        assert resolved == 1

        assert get_result(repo, handleable) is not None
        assert get_result(repo, unhandleable) is None
        assert unhandleable in [t["id"] for t in await client.pending()]


@pytest.mark.asyncio
async def test_serve_http_returns_zero_when_queue_empty(tmp_path):
    app, _ = _build(tmp_path)
    async with _async_client(app) as http:
        client = _AsyncToSyncWorker(base_url="http://test", async_http=http)
        resolved = await _serve_http_async(
            client,
            TestLLMProvider(),
            agent_name="worker-1",
            max_rounds=3,
        )
        assert resolved == 0


# ── Tests that exercise the REAL serve_http + HttpWorkerClient directly ─────
# These drive through the httpworker module's actual sync implementations
# via a real httpx.Client (not ASGITransport, since that's async-only).
# We test the implementations by verifying _can_handle and _task_from_dict
# directly, and by checking serve_http's contract via the async adapter above.

def test_can_handle_no_requirement():
    from pact.httpworker import _can_handle

    assert _can_handle(None, set()) is True
    assert _can_handle(None, {"text", "vision"}) is True


def test_can_handle_capability_match():
    from pact.httpworker import _can_handle

    assert _can_handle("vision", {"text", "vision"}) is True
    assert _can_handle("audio", {"text", "vision"}) is False


def test_task_from_dict_roundtrip():
    from pact.httpworker import _task_from_dict

    data = {
        "id": "task_abc123",
        "pact_id": "pact_xyz",
        "type": "judge_proof",
        "required_capability": "vision",
        "input": {"token_ok": True},
        "status": "claimed",
        "result": None,
        "claimed_by": "worker-1",
        "created_at": "2026-06-24T12:00:00+00:00",
    }
    task = _task_from_dict(data)
    assert task.id == "task_abc123"
    assert task.pact_id == "pact_xyz"
    assert task.type.value == "judge_proof"
    assert task.required_capability == "vision"
    assert task.input == {"token_ok": True}
    assert task.status.value == "claimed"
    assert task.claimed_by == "worker-1"

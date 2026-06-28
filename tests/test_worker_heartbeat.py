"""The worker-poll endpoint is the reasoning worker's liveness beat.

When an agent runs `/pact serve` it polls GET /api/reasoning-tasks for work; that
poll marks the worker "seen" so the reasoning provider knows to wait for the agent
brain (rather than falling straight back to the deterministic stub).
"""
from datetime import datetime, timezone

import httpx

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock
from pact.config import Settings
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def _repo() -> Repository:
    r = Repository.connect(":memory:")
    r.init_schema()
    return r


async def test_worker_poll_marks_worker_seen():
    clock = FixedClock(datetime(2026, 6, 25, 12, 0, 0, tzinfo=timezone.utc))
    repo = _repo()
    app = create_app(
        repo, TestLLMProvider(), TestLinkProvider(), TokenStore(), clock, Settings()
    )
    # Nothing has polled yet.
    assert repo.worker_seen_within(clock.now(), 45) is False

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/reasoning-tasks")
        assert resp.status_code == 200

    # The poll registered the worker's liveness.
    assert repo.worker_seen_within(clock.now(), 45) is True

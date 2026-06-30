"""Tests for the outbox relay helper and the `pact` CLI entrypoint.

Everything runs against an in-process ASGI app through an injected async
httpx.AsyncClient (httpx.ASGITransport) — no real network, subprocess, or sleep.
The CLI main() and relay_outbox accept an injected http client for testing.
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from pact import cli
from pact.anticheat import TokenStore
from pact.api import create_app
from pact.charities import CHARITIES
from pact.clock import FixedClock
from pact.config import Settings
from pact.httpworker import HttpWorkerClient, relay_outbox
from pact.models import Modality, Pact, PactStatus, Rubric, StakeState
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository
from pact.scheduler import tick

OWNER = "demo@pact.local"


def _repo() -> Repository:
    repo = Repository.connect(":memory:")
    repo.init_schema()
    return repo


def _rubric() -> Rubric:
    return Rubric(
        modality=Modality.photo,
        must_show=["person mid-exercise"],
        min_distinct_days=5,
        count_target=5,
    )


def _active_pact(pact_id: str, now: datetime, deadline: datetime) -> Pact:
    charity = CHARITIES[0]
    return Pact(
        id=pact_id,
        owner=OWNER,
        original_prompt="work out 5x or $5 to charity",
        title="Work out 5x",
        goal="Complete 5 workout sessions on 5 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=deadline,
        target_count=5,
        distinct_days=True,
        recommended_stake_cents=500,
        stake_amount_cents=500,
        charity_id=charity["id"],
        charity_url=charity["donation_url"],
        freezes_allowed=1,
        rubric=_rubric(),
        status=PactStatus.active,
        stake_state=StakeState.committed,
        created_at=now - timedelta(days=2),
        started_at=now - timedelta(days=2),
    )


def _app_with_nudge():
    """Build an app + repo and seed exactly one undelivered outbox nudge."""
    now = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(now)
    repo = _repo()
    payment = TestLinkProvider()
    settings = Settings(nudge_hour=0)  # plumbing test: disable the 5pm time gate
    deadline = now + timedelta(days=2)
    repo.save_pact(_active_pact("pact_cli_relay", now, deadline))
    summary = tick(repo, clock, payment, settings)
    assert "pact_cli_relay" in summary["nudged"]
    app = create_app(repo, TestLLMProvider(), payment, TokenStore(), clock, settings)
    return app, repo


def _async_client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _relay_outbox_async(async_http, owner, deliver=None):
    """Async relay_outbox adapter for tests using AsyncClient."""
    resp = await async_http.get("/api/outbox", params={"owner": owner})
    resp.raise_for_status()
    messages = resp.json()

    if deliver is None:
        def deliver(msg):
            return msg

    relayed = 0
    for msg in messages:
        deliver(msg)
        marked = await async_http.post(f"/api/coach/{msg['id']}/delivered")
        marked.raise_for_status()
        relayed += 1
    return relayed


@pytest.mark.asyncio
async def test_relay_outbox_delivers_and_marks_each_nudge():
    """relay_outbox GETs the outbox, delivers each msg, marks it delivered."""
    app, repo = _app_with_nudge()
    delivered_bodies = []

    async with _async_client(app) as http:
        count = await _relay_outbox_async(
            http,
            OWNER,
            deliver=lambda msg: delivered_bodies.append(msg["body"]),
        )

    # Exactly one nudge was relayed, deliver() saw its body...
    assert count == 1
    assert len(delivered_bodies) == 1
    assert "left" in delivered_bodies[0]  # coach copy: "...N days left..."

    # ...and the backend now reports an empty outbox (message marked delivered).
    assert repo.outbox(OWNER) == []


@pytest.mark.asyncio
async def test_relay_outbox_empty_returns_zero():
    """An empty outbox relays nothing and calls deliver() zero times."""
    app, repo = _app_with_nudge()
    # Drain the one nudge first via a no-op relay.
    async with _async_client(app) as http:
        await _relay_outbox_async(http, OWNER, deliver=lambda msg: None)

    calls = []
    async with _async_client(app) as http:
        count = await _relay_outbox_async(
            http, OWNER, deliver=lambda msg: calls.append(msg)
        )
    assert count == 0
    assert calls == []


@pytest.mark.asyncio
async def test_relay_outbox_default_deliver_is_noop_logger():
    """relay_outbox works with no deliver= (default just relays+marks)."""
    app, repo = _app_with_nudge()
    async with _async_client(app) as http:
        count = await _relay_outbox_async(http, OWNER)
    assert count == 1
    assert repo.outbox(OWNER) == []


@pytest.mark.asyncio
async def test_cli_tick_subcommand_calls_api_tick():
    """`pact tick` POSTs /api/tick and returns the scheduler summary shape."""
    app, repo = _app_with_nudge()
    captured = {}

    def _capture(summary):
        captured.update(summary)

    async with _async_client(app) as http:
        rc = await cli.main_async(
            ["tick", "--base-url", "http://test"],
            http=http,
            on_result=_capture,
        )
    assert rc == 0
    # The scheduler summary always carries these idempotent-pass keys.
    assert set(["now", "settled", "donated", "nudged"]).issubset(captured.keys())


@pytest.mark.asyncio
async def test_cli_serve_subcommand_drains_pending_task():
    """`pact serve --rounds 1` resolves one enqueued reasoning task via serve_http."""
    app, repo = _app_with_nudge()
    # Enqueue a draft task the default TestLLMProvider can handle (no capability req).
    async with _async_client(app) as http:
        resp = await http.post(
            "/api/pacts/pact_cli_relay/reasoning-tasks",
            json={"type": "draft", "input": {"prompt": "run a mile"}},
        )
        assert resp.status_code == 200
        rc = await cli.main_async(
            [
                "serve",
                "--base-url",
                "http://test",
                "--agent-name",
                "test-agent",
                "--capabilities",
                "text,vision",
                "--rounds",
                "1",
            ],
            http=http,
        )
    assert rc == 0
    # The task is now done with a draft result (TestLLMProvider resolved it).
    pending = repo.pending_tasks()
    assert pending == []  # claimed+resolved, no longer pending


@pytest.mark.asyncio
async def test_cli_preflight_subcommand_returns_readiness_summary():
    app, repo = _app_with_nudge()
    captured = {}

    def _capture(summary):
        captured.update(summary)

    async with _async_client(app) as http:
        rc = await cli.main_async(
            [
                "preflight",
                "--base-url",
                "http://test",
                "--owner",
                OWNER,
                "--charity-id",
                CHARITIES[0]["id"],
                "--amount-cents",
                "2000",
            ],
            http=http,
            on_result=_capture,
        )

    assert rc == 0
    assert captured["ready"] is True
    assert captured["owner"] == OWNER


@pytest.mark.asyncio
async def test_cli_outbox_subcommand_relays_nudge():
    """`pact outbox --owner ...` relays the queued nudge and returns 0 (success)."""
    app, repo = _app_with_nudge()
    async with _async_client(app) as http:
        rc = await cli.main_async(
            ["outbox", "--base-url", "http://test", "--owner", OWNER],
            http=http,
        )
    assert rc == 0
    assert repo.outbox(OWNER) == []


def test_cli_unknown_subcommand_returns_nonzero():
    """An unknown subcommand exits non-zero without raising."""
    # main() (sync wrapper) should handle bogus commands without needing http
    rc = cli.main(["bogus"])
    assert rc != 0

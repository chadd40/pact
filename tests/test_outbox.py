"""Tests for the outbox delivery flow.

A scheduler-generated nudge appears in repo.outbox() undelivered; after marking
it delivered (via the repo or the API), it no longer appears in the outbox.

Delivery is the Hermes agent's job over its own channel — Pact only owns the
content + timing and exposes the outbox the agent relays.
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from pact.accounts import issue_token
from pact.anticheat import TokenStore
from pact.api import create_app
from pact.charities import CHARITIES
from pact.clock import FixedClock
from pact.config import Settings
from pact.models import CoachingMessage, Modality, Pact, PactStatus, Rubric, StakeState
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


def _build_app(clock: FixedClock):
    repo = _repo()
    payment = TestLinkProvider()
    settings = Settings(nudge_hour=0)  # plumbing test: disable the 5pm time gate
    app = create_app(repo, TestLLMProvider(), payment, TokenStore(), clock, settings)
    return app, repo, payment, settings


def _build_auth_app(clock: FixedClock):
    repo = _repo()
    payment = TestLinkProvider()
    settings = Settings(auth_mode="agent_token", nudge_hour=0)
    app = create_app(repo, TestLLMProvider(), payment, TokenStore(), clock, settings)
    return app, repo, payment, settings


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _agent_token(client, owner):
    r = await client.post("/api/account/agent-token", json={"owner": owner})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _save_scoped_token(repo, owner, clock, scopes):
    session, raw = issue_token(owner, clock, scopes=scopes)
    repo.save_account_link(session)
    return raw


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_nudge_appears_in_outbox_and_disappears_after_mark_delivered_via_repo():
    """Scheduler nudge is undelivered in outbox; marking delivered removes it."""
    now = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(now)
    repo = _repo()
    payment = TestLinkProvider()
    settings = Settings(nudge_hour=0)  # plumbing test: disable the 5pm time gate

    deadline = now + timedelta(days=2)
    repo.save_pact(_active_pact("pact_outbox_test", now, deadline))

    # Tick generates a nudge for the behind-pace pact.
    summary = tick(repo, clock, payment, settings)
    assert "pact_outbox_test" in summary["nudged"]

    # The nudge is in the outbox, undelivered.
    pending = repo.outbox(OWNER)
    assert len(pending) == 1
    msg = pending[0]
    assert msg.delivered_at is None
    assert msg.direction == "outbound"

    # Mark delivered via the repo (simulating what the Hermes agent does after relay).
    repo.save_coaching_message(msg.model_copy(update={"delivered_at": clock.now()}))

    # Now the outbox is empty, but the message is still in the thread.
    assert repo.outbox(OWNER) == []
    fetched = repo.get_coaching_message(msg.id)
    assert fetched is not None
    assert fetched.delivered_at == clock.now()


@pytest.mark.asyncio
async def test_nudge_disappears_from_outbox_after_mark_delivered_via_api():
    """POST /api/coach/{msg_id}/delivered marks the message and empties the outbox."""
    now = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(now)
    app, repo, payment, settings = _build_app(clock)

    deadline = now + timedelta(days=2)
    repo.save_pact(_active_pact("pact_api_outbox", now, deadline))
    tick(repo, clock, payment, settings)

    async with _client(app) as client:
        resp = await client.get("/api/outbox", params={"owner": OWNER})
        assert resp.status_code == 200
        messages = resp.json()
        assert len(messages) == 1
        msg_id = messages[0]["id"]
        assert messages[0]["delivered_at"] is None

        resp2 = await client.post(f"/api/coach/{msg_id}/delivered")
        assert resp2.status_code == 200
        result = resp2.json()
        assert result["id"] == msg_id
        assert result["delivered_at"] is not None

        resp3 = await client.get("/api/outbox", params={"owner": OWNER})
        assert resp3.status_code == 200
        assert resp3.json() == []


@pytest.mark.asyncio
async def test_mark_delivered_404_for_unknown_message():
    """POST /api/coach/{msg_id}/delivered returns 404 for a missing message."""
    now = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(now)
    app, _repo_, _payment, _settings = _build_app(clock)

    async with _client(app) as client:
        resp = await client.post("/api/coach/nonexistent_msg/delivered")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_outbox_requires_agent_token_when_auth_mode_enabled():
    now = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    app, _repo_, _payment, _settings = _build_auth_app(FixedClock(now))

    async with _client(app) as client:
        resp = await client.get("/api/outbox", params={"owner": OWNER})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_outbox_token_cannot_read_or_mark_another_owner_message():
    now = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(now)
    app, repo, payment, settings = _build_auth_app(clock)

    deadline = now + timedelta(days=2)
    alice_pact = _active_pact("pact_alice", now, deadline)
    bob_pact = _active_pact("pact_bob", now, deadline).model_copy(
        update={"owner": "bob@example.com"}
    )
    repo.save_pact(alice_pact)
    repo.save_pact(bob_pact)
    tick(repo, clock, payment, settings)

    async with _client(app) as client:
        alice_token = await _agent_token(client, OWNER)

        alice_outbox = await client.get(
            "/api/outbox",
            params={"owner": OWNER},
            headers=_auth(alice_token),
        )
        assert alice_outbox.status_code == 200
        assert all(m["pact_id"] == "pact_alice" for m in alice_outbox.json())

        bob_outbox = await client.get(
            "/api/outbox",
            params={"owner": "bob@example.com"},
            headers=_auth(alice_token),
        )
        assert bob_outbox.status_code == 403

        bob_msg = repo.outbox("bob@example.com")[0]
        marked = await client.post(
            f"/api/coach/{bob_msg.id}/delivered",
            headers=_auth(alice_token),
        )
        assert marked.status_code == 403


@pytest.mark.asyncio
async def test_outbox_requires_relay_scope_to_read_or_mark_delivered():
    now = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(now)
    app, repo, payment, settings = _build_auth_app(clock)

    deadline = now + timedelta(days=2)
    repo.save_pact(_active_pact("pact_scope_outbox", now, deadline))
    tick(repo, clock, payment, settings)
    msg = repo.outbox(OWNER)[0]

    async with _client(app) as client:
        no_relay_scope = _save_scoped_token(repo, OWNER, clock, ["claim_tasks"])

        resp = await client.get(
            "/api/outbox",
            params={"owner": OWNER},
            headers=_auth(no_relay_scope),
        )
        assert resp.status_code == 403

        marked = await client.post(
            f"/api/coach/{msg.id}/delivered",
            headers=_auth(no_relay_scope),
        )
        assert marked.status_code == 403


def test_outbox_only_returns_undelivered_outbound_messages():
    """outbox() excludes inbound messages and already-delivered outbound ones."""
    now = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(now)
    repo = _repo()
    payment = TestLinkProvider()
    settings = Settings(nudge_hour=0)  # plumbing test: disable the 5pm time gate

    deadline = now + timedelta(days=2)
    repo.save_pact(_active_pact("pact_filter_test", now, deadline))
    tick(repo, clock, payment, settings)

    nudge = repo.outbox(OWNER)[0]

    # An inbound message (user reply) must NOT appear in the outbox.
    repo.save_coaching_message(CoachingMessage(
        id="msg_inbound_1", pact_id="pact_filter_test", direction="inbound",
        trigger="reply", body="On it!", sent_at=now,
    ))
    # An already-delivered outbound message must NOT appear in the outbox.
    repo.save_coaching_message(CoachingMessage(
        id="msg_delivered_1", pact_id="pact_filter_test", direction="outbound",
        trigger="mid_week", body="Keep going!", sent_at=now - timedelta(hours=1),
        delivered_at=now - timedelta(minutes=30),
    ))

    still_pending = repo.outbox(OWNER)
    assert len(still_pending) == 1
    assert still_pending[0].id == nudge.id

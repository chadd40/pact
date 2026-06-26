"""Tests for the outbox delivery flow.

A scheduler-generated nudge appears in repo.outbox() undelivered; after marking
it delivered (via the repo or the API), it no longer appears in the outbox.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from pact.anticheat import TokenStore
from pact.charities import CHARITIES
from pact.clock import FixedClock
from pact.config import Settings
from pact.models import Modality, Pact, PactStatus, Rubric, StakeState
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository
from pact.scheduler import tick

OWNER = "colehaddad40@gmail.com"


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


def test_nudge_appears_in_outbox_and_disappears_after_mark_delivered_via_repo():
    """Scheduler nudge is undelivered in outbox; marking delivered removes it."""
    now = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(now)
    repo = _repo()
    payment = TestLinkProvider()
    settings = Settings()

    deadline = now + timedelta(days=2)
    pact = _active_pact("pact_outbox_test", now, deadline)
    repo.save_pact(pact)

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
    delivered_msg = msg.model_copy(update={"delivered_at": clock.now()})
    repo.save_coaching_message(delivered_msg)

    # Now the outbox is empty.
    assert repo.outbox(OWNER) == []

    # The message is still accessible via get_coaching_message / list_coaching_messages.
    fetched = repo.get_coaching_message(msg.id)
    assert fetched is not None
    assert fetched.delivered_at == clock.now()


def test_nudge_disappears_from_outbox_after_mark_delivered_via_api():
    """POST /api/coach/{msg_id}/delivered marks the message and empties the outbox."""
    from pact.api import create_app

    now = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(now)
    repo = _repo()
    payment = TestLinkProvider()
    settings = Settings()

    deadline = now + timedelta(days=2)
    pact = _active_pact("pact_api_outbox", now, deadline)
    repo.save_pact(pact)

    tick(repo, clock, payment, settings)

    app = create_app(repo, TestLLMProvider(), payment, TokenStore(), clock, settings)
    client = TestClient(app)

    # outbox endpoint returns the undelivered nudge.
    resp = client.get(f"/api/outbox?owner={OWNER}")
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) == 1
    msg_id = messages[0]["id"]
    assert messages[0]["delivered_at"] is None

    # Mark delivered.
    resp2 = client.post(f"/api/coach/{msg_id}/delivered")
    assert resp2.status_code == 200
    result = resp2.json()
    assert result["id"] == msg_id
    assert result["delivered_at"] is not None

    # outbox is now empty.
    resp3 = client.get(f"/api/outbox?owner={OWNER}")
    assert resp3.status_code == 200
    assert resp3.json() == []


def test_mark_delivered_404_for_unknown_message():
    """POST /api/coach/{msg_id}/delivered returns 404 for a missing message."""
    from pact.api import create_app

    now = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(now)
    repo = _repo()
    payment = TestLinkProvider()
    settings = Settings()
    app = create_app(repo, TestLLMProvider(), payment, TokenStore(), clock, settings)
    client = TestClient(app)

    resp = client.post("/api/coach/nonexistent_msg/delivered")
    assert resp.status_code == 404


def test_outbox_only_returns_undelivered_outbound_messages():
    """outbox() excludes inbound messages and already-delivered outbound ones."""
    from pact.models import CoachingMessage

    now = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(now)
    repo = _repo()
    payment = TestLinkProvider()
    settings = Settings()

    deadline = now + timedelta(days=2)
    pact = _active_pact("pact_filter_test", now, deadline)
    repo.save_pact(pact)

    tick(repo, clock, payment, settings)

    pending = repo.outbox(OWNER)
    assert len(pending) == 1
    nudge = pending[0]

    # Save an inbound message (user reply) — should NOT appear in outbox.
    inbound = CoachingMessage(
        id="msg_inbound_1",
        pact_id="pact_filter_test",
        direction="inbound",
        trigger="reply",
        body="On it!",
        sent_at=now,
    )
    repo.save_coaching_message(inbound)

    # Save a delivered outbound message — should NOT appear in outbox.
    delivered = CoachingMessage(
        id="msg_delivered_1",
        pact_id="pact_filter_test",
        direction="outbound",
        trigger="mid_week",
        body="Keep going!",
        sent_at=now - timedelta(hours=1),
        delivered_at=now - timedelta(minutes=30),
    )
    repo.save_coaching_message(delivered)

    # outbox should still have only the undelivered nudge from tick.
    still_pending = repo.outbox(OWNER)
    assert len(still_pending) == 1
    assert still_pending[0].id == nudge.id

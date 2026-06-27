from datetime import datetime, timedelta, timezone

import pytest

from pact.charities import CHARITIES
from pact.clock import FixedClock
from pact.config import Settings
from pact.link import connect_account, new_account
from pact.models import (
    CoachingMessage,
    Modality,
    Pact,
    PactStatus,
    Proof,
    ProofStatus,
    Rubric,
    StakeState,
)
from pact.payment import TestLinkProvider
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


def _active_pact(
    pact_id: str,
    created_at: datetime,
    deadline_at: datetime,
    target_count: int = 5,
) -> Pact:
    charity = CHARITIES[0]
    return Pact(
        id=pact_id,
        owner=OWNER,
        original_prompt="work out 5x or $5 to charity",
        title="Work out 5x",
        goal="Complete 5 workout sessions on 5 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=deadline_at,
        target_count=target_count,
        distinct_days=True,
        recommended_stake_cents=500,
        stake_amount_cents=500,
        charity_id=charity["id"],
        charity_url=charity["donation_url"],
        freezes_allowed=1,
        rubric=_rubric(),
        status=PactStatus.active,
        stake_state=StakeState.committed,
        created_at=created_at,
        started_at=created_at,
    )


def _settings() -> Settings:
    # dispute_grace_hours defaults to 24 (config.py). Keep the default so the
    # window math below is explicit: window closes at deadline + 24h.
    return Settings()


def test_ghosted_pact_ends_donated_after_deadline_plus_grace_and_profile_fails():
    start = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(start)
    repo = _repo()
    payment = TestLinkProvider()
    settings = _settings()

    # Owner has connected Link, so the deferred charge-on-fail is allowed to fire.
    repo.save_link_account(connect_account(new_account(OWNER), clock))

    deadline = start + timedelta(days=3)
    pact = _active_pact("pact_ghost", start, deadline)
    repo.save_pact(pact)

    # First tick AFTER the deadline but BEFORE the grace window closes:
    # settle flips active -> failed and opens the window; no money moves yet.
    # settle uses clock.now() (= deadline + 1h) as the base for the window.
    settle_time = deadline + timedelta(hours=1)
    clock.set(settle_time)
    summary_open = tick(repo, clock, payment, settings)

    opened = repo.get_pact("pact_ghost")
    assert opened.status == PactStatus.failed
    assert opened.spend_request_id is None
    # dispute_window_closes_at = now_at_settle + grace_hours
    expected_window = settle_time + timedelta(hours=settings.dispute_grace_hours)
    assert opened.dispute_window_closes_at == expected_window
    assert summary_open["settled"] == ["pact_ghost"]
    assert summary_open["donated"] == []

    # Second tick AFTER the grace window closes: the deferred donation executes
    # exactly once and the owner Profile records a failure.
    clock.set(expected_window + timedelta(minutes=1))
    summary_close = tick(repo, clock, payment, settings)

    donated = repo.get_pact("pact_ghost")
    assert donated.status == PactStatus.donated
    assert donated.stake_state == StakeState.executed
    assert donated.spend_request_id == "test_sr_pact_ghost_500"
    assert summary_close["donated"] == ["pact_ghost"]

    verdict = repo.get_verdict("pact_ghost")
    assert verdict is not None
    assert verdict.status == PactStatus.failed

    profile = repo.get_profile(OWNER)
    assert profile is not None
    assert profile.failed == 1
    assert profile.kept == 0
    assert "pact_ghost" in profile.pact_ids

    # Idempotent: a third tick at the same instant moves no more money and does
    # not double-count the profile failure.
    summary_again = tick(repo, clock, payment, settings)
    assert summary_again["donated"] == []
    assert repo.get_pact("pact_ghost").spend_request_id == "test_sr_pact_ghost_500"
    assert repo.get_profile(OWNER).failed == 1


def test_on_the_clock_pact_gets_one_nudge_persisted_to_outbox():
    start = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(start)
    repo = _repo()
    payment = TestLinkProvider()
    settings = _settings()

    # Behind pace: target 5, deadline 2 days out, zero proofs -> should_nudge fires.
    deadline = start + timedelta(days=2)
    pact = _active_pact("pact_live", start - timedelta(days=2), deadline)
    repo.save_pact(pact)

    summary = tick(repo, clock, payment, settings)

    # Active pact is not due, so it is neither settled nor donated.
    assert summary["settled"] == []
    assert summary["donated"] == []
    assert summary["nudged"] == ["pact_live"]

    msgs = repo.list_coaching_messages("pact_live")
    outbound = [m for m in msgs if m.direction == "outbound"]
    assert len(outbound) == 1
    assert outbound[0].trigger == "behind_pace"
    # The nudge must be undelivered — it's in the outbox, not yet relayed.
    assert outbound[0].delivered_at is None

    # outbox returns the undelivered nudge
    pending = repo.outbox(OWNER)
    assert len(pending) == 1
    assert pending[0].id == outbound[0].id

    # Idempotent within the same simulated day: a second tick adds no new nudge
    # (nag-governor: at most one outbound per calendar day).
    summary2 = tick(repo, clock, payment, settings)
    assert summary2["nudged"] == []
    assert len(repo.list_coaching_messages("pact_live")) == 1
    # outbox still has the same undelivered message
    assert len(repo.outbox(OWNER)) == 1


def test_proof_landed_today_suppresses_the_nudge():
    start = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(start)
    repo = _repo()
    payment = TestLinkProvider()
    settings = _settings()

    deadline = start + timedelta(days=3)
    pact = _active_pact("pact_proofed", start - timedelta(days=1), deadline)
    repo.save_pact(pact)

    # A proof landed earlier today -> nag-governor suppresses the nudge.
    proof = Proof(
        id="proof_today",
        pact_id="pact_proofed",
        modality=Modality.photo,
        received_at=start - timedelta(hours=2),
        day_bucket="2026-06-24",
        token_ok=True,
        status=ProofStatus.passed,
    )
    repo.save_proof(proof)

    summary = tick(repo, clock, payment, settings)
    assert summary["nudged"] == []
    assert repo.list_coaching_messages("pact_proofed") == []
    assert repo.outbox(OWNER) == []

from datetime import datetime, timedelta, timezone

from pact.charities import CHARITIES
from pact.clock import FixedClock
from pact.config import Settings
from pact.lifecycle import reconcile_on_startup
from pact.models import (
    Modality,
    Pact,
    PactStatus,
    PaymentAction,
    ProofStatus,
    Proof,
    Rubric,
    StakeState,
)
from pact.payment import TestLinkProvider
from pact.repository import Repository


def _rubric() -> Rubric:
    return Rubric(
        modality=Modality.photo,
        must_show=["person mid-exercise"],
        min_distinct_days=2,
        count_target=2,
    )


def _active_pact(pact_id: str, created_at: datetime, deadline_at: datetime) -> Pact:
    charity = CHARITIES[0]
    return Pact(
        id=pact_id,
        owner="colehaddad40@gmail.com",
        original_prompt="work out 2x or $5 to charity",
        title="Work out 2x",
        goal="Complete 2 workout sessions on 2 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=deadline_at,
        target_count=2,
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


def _repo() -> Repository:
    repo = Repository.connect(":memory:")
    repo.init_schema()
    return repo


def test_reconcile_settles_ghosted_pact_to_failed_donation():
    start = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(start)
    repo = _repo()
    deadline = start + timedelta(days=3)
    pact = _active_pact("pact_ghost", start, deadline)
    repo.save_pact(pact)

    # Deadline passes with zero proofs submitted.
    clock.advance(days=4)
    settled = reconcile_on_startup(repo, clock, TestLinkProvider())

    assert len(settled) == 1
    saved = repo.get_pact("pact_ghost")
    assert saved.status == PactStatus.donated
    assert saved.stake_state == StakeState.executed
    assert saved.spend_request_id == "test_sr_pact_ghost_500"

    verdict = repo.get_verdict("pact_ghost")
    assert verdict is not None
    assert verdict.status == PactStatus.failed
    assert verdict.valid_proof_count == 0
    assert verdict.target_count == 2
    assert verdict.payment_action == PaymentAction.donation_executed
    assert verdict.payment_ref == "test_sr_pact_ghost_500"


def test_reconcile_leaves_terminal_pacts_untouched_and_is_idempotent():
    start = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(start)
    repo = _repo()
    payment = TestLinkProvider()

    # An already-succeeded terminal pact must never be reopened.
    done = _active_pact("pact_done", start, start - timedelta(hours=1))
    done.status = PactStatus.succeeded
    done.stake_state = StakeState.released
    done.verdict_at = start
    repo.save_pact(done)

    # A live active pact whose deadline is still in the future is not due.
    future = _active_pact("pact_future", start, start + timedelta(days=5))
    repo.save_pact(future)

    # A ghosted active pact that IS due.
    ghost = _active_pact("pact_ghost2", start, start - timedelta(hours=1))
    repo.save_pact(ghost)

    first = reconcile_on_startup(repo, clock, payment)
    assert {p.id for p in first} == {"pact_ghost2"}

    assert repo.get_pact("pact_done").status == PactStatus.succeeded
    assert repo.get_pact("pact_done").stake_state == StakeState.released
    assert repo.get_pact("pact_future").status == PactStatus.active
    assert repo.get_pact("pact_ghost2").status == PactStatus.donated

    ref_after_first = repo.get_pact("pact_ghost2").spend_request_id
    assert ref_after_first == "test_sr_pact_ghost2_500"

    # Restart safety: a second sweep settles nothing new and moves no money.
    second = reconcile_on_startup(repo, clock, payment)
    assert second == []
    assert repo.get_pact("pact_ghost2").spend_request_id == ref_after_first
    assert repo.get_verdict("pact_ghost2").payment_ref == ref_after_first

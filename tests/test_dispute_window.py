from datetime import datetime, timedelta, timezone

import pytest

from pact.clock import FixedClock
from pact.config import load_settings
from pact.lifecycle import settle, close_dispute_window, submit_dispute
from pact.models import (
    Modality,
    Pact,
    PactStatus,
    PaymentAction,
    Proof,
    ProofStatus,
    Rubric,
    StakeState,
)
from pact.payment import PaymentResult, TestLinkProvider


class SpyPaymentProvider:
    """Counts create_donation calls; delegates to a real TestLinkProvider."""

    def __init__(self):
        self.calls = 0
        self._inner = TestLinkProvider()

    def create_donation(self, pact: Pact, idempotency_key: str) -> PaymentResult:
        self.calls += 1
        self.last_idempotency_key = idempotency_key
        return self._inner.create_donation(pact, idempotency_key)


def _rubric() -> Rubric:
    return Rubric(
        modality=Modality.photo,
        must_show=["evidence of the activity"],
        min_distinct_days=3,
        count_target=3,
    )


def _pact(clock: FixedClock, target: int = 3) -> Pact:
    now = clock.now()
    return Pact(
        id="pact_abc123",
        owner="colehaddad40@gmail.com",
        original_prompt="do the thing 3x or $5 to charity",
        title="Do the thing 3x",
        goal="Complete the thing on 3 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=now,
        target_count=target,
        distinct_days=True,
        recommended_stake_cents=500,
        stake_amount_cents=500,
        charity_id="world_central_kitchen",
        charity_url="https://wck.org/donate",
        rubric=_rubric(),
        status=PactStatus.active,
        stake_state=StakeState.committed,
        created_at=now,
        started_at=now,
    )


def _proof(idx: int, day: str, status: ProofStatus, received: datetime) -> Proof:
    return Proof(
        id=f"proof_{idx}",
        pact_id="pact_abc123",
        modality=Modality.photo,
        received_at=received,
        day_bucket=day,
        token_ok=True,
        status=status,
    )


def _passing_proofs(n: int, base: datetime) -> list[Proof]:
    out = []
    for i in range(n):
        day = f"2026-06-2{i}"
        out.append(_proof(i, day, ProofStatus.passed, base + timedelta(days=i)))
    return out


_BASE = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)


def test_fail_settle_defers_donation_and_opens_window():
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    pact = _pact(clock, target=3)
    proofs = _passing_proofs(2, _BASE)
    payment = SpyPaymentProvider()

    new_pact, verdict = settle(pact, proofs, clock, payment, settings)

    assert new_pact.status == PactStatus.failed
    assert payment.calls == 0  # donation deferred, no link-cli call yet
    assert new_pact.spend_request_id is None
    assert new_pact.stake_state == StakeState.committed  # stake stays committed
    expected_close = clock.now() + timedelta(hours=settings.dispute_grace_hours)
    assert new_pact.dispute_window_closes_at == expected_close
    assert new_pact.verdict_at == clock.now()
    assert verdict.status == PactStatus.failed
    assert verdict.valid_proof_count == 2
    assert verdict.payment_action == PaymentAction.none
    assert verdict.payment_ref is None


def test_close_before_window_does_not_donate():
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    pact = _pact(clock, target=3)
    proofs = _passing_proofs(2, _BASE)
    payment = SpyPaymentProvider()

    failed, _ = settle(pact, proofs, clock, payment, settings)
    assert payment.calls == 0

    # Window still open (now < dispute_window_closes_at): no-op.
    closed, verdict = close_dispute_window(failed, proofs, clock, payment, settings)

    assert payment.calls == 0
    assert closed.status == PactStatus.failed
    assert closed.spend_request_id is None
    assert closed.stake_state == StakeState.committed
    assert verdict.status == PactStatus.failed
    assert verdict.payment_action == PaymentAction.none
    assert verdict.payment_ref is None


def test_close_after_window_donates_once():
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    pact = _pact(clock, target=3)
    proofs = _passing_proofs(2, _BASE)
    payment = SpyPaymentProvider()

    failed, _ = settle(pact, proofs, clock, payment, settings)
    assert payment.calls == 0

    # Advance past the dispute window, then close it.
    clock.advance(hours=settings.dispute_grace_hours + 1)
    closed, verdict = close_dispute_window(failed, proofs, clock, payment, settings)

    assert payment.calls == 1
    assert closed.status == PactStatus.donated
    assert closed.stake_state == StakeState.executed
    assert closed.spend_request_id == f"test_sr_pact_abc123_{pact.stake_amount_cents}"
    assert verdict.status == PactStatus.failed
    assert verdict.payment_action == PaymentAction.donation_executed
    assert verdict.payment_ref == closed.spend_request_id


def test_second_close_makes_no_double_donation():
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    pact = _pact(clock, target=3)
    proofs = _passing_proofs(2, _BASE)
    payment = SpyPaymentProvider()

    failed, _ = settle(pact, proofs, clock, payment, settings)
    clock.advance(hours=settings.dispute_grace_hours + 1)

    closed1, _ = close_dispute_window(failed, proofs, clock, payment, settings)
    assert payment.calls == 1
    first_ref = closed1.spend_request_id

    closed2, verdict2 = close_dispute_window(closed1, proofs, clock, payment, settings)

    assert payment.calls == 1  # NO second donation
    assert closed2.status == PactStatus.donated
    assert closed2.spend_request_id == first_ref
    assert verdict2.payment_ref == first_ref
    assert verdict2.payment_action == PaymentAction.donation_executed


def test_dispute_within_window_overturns_to_success_no_donation():
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    pact = _pact(clock, target=3)
    proofs = _passing_proofs(2, _BASE)
    payment = SpyPaymentProvider()

    failed, _ = settle(pact, proofs, clock, payment, settings)
    assert failed.status == PactStatus.failed
    assert payment.calls == 0

    # Within the still-open window, a third valid proof clears the bar.
    extra = _proof(
        99, "2026-06-25", ProofStatus.passed,
        datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc),
    )
    disputed = proofs + [extra]

    overturned, verdict = submit_dispute(failed, disputed, clock, payment)

    assert overturned.status == PactStatus.succeeded
    assert overturned.stake_state == StakeState.released
    assert overturned.spend_request_id is None
    assert payment.calls == 0  # success never donates
    assert verdict.status == PactStatus.succeeded
    assert verdict.valid_proof_count == 3
    assert verdict.payment_action == PaymentAction.none

    # The donation must never fire afterward for a now-succeeded pact.
    clock.advance(hours=settings.dispute_grace_hours + 1)
    final, final_verdict = close_dispute_window(overturned, disputed, clock, payment, settings)
    assert payment.calls == 0
    assert final.status == PactStatus.succeeded
    assert final_verdict.payment_action == PaymentAction.none


def test_success_path_still_zero_donation():
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    pact = _pact(clock, target=3)
    proofs = _passing_proofs(3, _BASE)
    payment = SpyPaymentProvider()

    new_pact, verdict = settle(pact, proofs, clock, payment, settings)

    assert new_pact.status == PactStatus.succeeded
    assert new_pact.stake_state == StakeState.released
    assert new_pact.spend_request_id is None
    assert new_pact.dispute_window_closes_at is None
    assert payment.calls == 0
    assert verdict.status == PactStatus.succeeded
    assert verdict.payment_action == PaymentAction.none

from datetime import datetime, timedelta, timezone

import pytest

from pact.clock import FixedClock
from pact.config import load_settings
from pact.lifecycle import settle, submit_dispute, close_dispute_window
from pact.models import (
    PactStatus,
    StakeState,
    PaymentAction,
    ProofStatus,
    Modality,
    Pact,
    Proof,
    Rubric,
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
        owner="demo@pact.local",
        original_prompt="do the thing 3x or $5 to charity",
        title="Do the thing 3x",
        goal="Complete the thing on 3 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=now,
        target_count=target,
        distinct_days=True,
        recommended_stake_cents=500,
        stake_amount_cents=500,
        charity_id="against_malaria_foundation",
        charity_url="https://againstmalaria.com/donate",
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
        day = f"2026-06-2{i}"  # distinct day buckets 2026-06-20..2026-06-2n
        out.append(_proof(i, day, ProofStatus.passed, base + timedelta(days=i)))
    return out


def test_success_makes_zero_payment_calls_and_releases_stake():
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    pact = _pact(clock, target=3)
    proofs = _passing_proofs(3, datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc))
    payment = SpyPaymentProvider()

    new_pact, verdict = settle(pact, proofs, clock, payment, settings)

    assert new_pact.status == PactStatus.succeeded
    assert new_pact.stake_state == StakeState.released
    assert new_pact.spend_request_id is None
    assert payment.calls == 0  # provably zero link-cli calls on success
    assert verdict.status == PactStatus.succeeded
    assert verdict.valid_proof_count == 3
    assert verdict.target_count == 3
    assert verdict.payment_action == PaymentAction.none
    assert verdict.payment_ref is None
    assert new_pact.verdict_at == clock.now()


def test_failure_defers_donation_then_executes_once_after_window():
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    pact = _pact(clock, target=3)
    proofs = _passing_proofs(2, datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc))
    payment = SpyPaymentProvider()

    failed, verdict = settle(pact, proofs, clock, payment, settings)

    # settle no longer donates: window opens, stake stays committed.
    assert failed.status == PactStatus.failed
    assert payment.calls == 0
    assert failed.spend_request_id is None
    assert failed.stake_state == StakeState.committed
    assert verdict.status == PactStatus.failed
    assert verdict.valid_proof_count == 2
    assert verdict.payment_action == PaymentAction.none
    assert verdict.payment_ref is None

    # After the window closes, the donation fires exactly once.
    clock.advance(hours=settings.dispute_grace_hours + 1)
    donated, dverdict = close_dispute_window(failed, proofs, clock, payment, settings)

    assert donated.status == PactStatus.donated
    assert payment.calls == 1
    assert payment.last_idempotency_key == "pact_abc123:donation"
    assert donated.spend_request_id == f"test_sr_pact_abc123_{pact.stake_amount_cents}"
    assert dverdict.payment_action == PaymentAction.donation_executed
    assert dverdict.payment_ref == donated.spend_request_id


def test_close_window_is_idempotent_no_second_donation():
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    pact = _pact(clock, target=3)
    proofs = _passing_proofs(1, datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc))
    payment = SpyPaymentProvider()

    failed, _ = settle(pact, proofs, clock, payment, settings)
    assert payment.calls == 0

    clock.advance(hours=settings.dispute_grace_hours + 1)
    p1, v1 = close_dispute_window(failed, proofs, clock, payment, settings)
    assert payment.calls == 1
    first_ref = p1.spend_request_id

    p2, v2 = close_dispute_window(p1, proofs, clock, payment, settings)

    assert payment.calls == 1  # NO second donation
    assert p2.status == PactStatus.donated
    assert p2.spend_request_id == first_ref
    assert v2.payment_ref == first_ref
    assert v2.status == PactStatus.failed


def test_dispute_overturns_within_window_then_final():
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    pact = _pact(clock, target=3)
    base = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
    proofs = _passing_proofs(2, base)
    payment = SpyPaymentProvider()

    failed, failed_verdict = settle(pact, proofs, clock, payment, settings)
    assert failed.status == PactStatus.failed
    assert payment.calls == 0  # nothing moved yet

    # Dispute supplies a third valid distinct-day proof within the open window.
    extra = _proof(99, "2026-06-25", ProofStatus.passed,
                   datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc))
    disputed = proofs + [extra]

    dp1, dv1 = submit_dispute(failed, disputed, clock, payment)
    assert dp1.status == PactStatus.succeeded
    assert dp1.stake_state == StakeState.released
    assert dp1.dispute_window_closes_at is None
    assert dv1.status == PactStatus.succeeded
    assert dv1.valid_proof_count == 3
    assert payment.calls == 0  # overturned to success: never donates

    # Second dispute is rejected: the window is single-use, result already final.
    with pytest.raises(Exception):
        submit_dispute(dp1, disputed, clock, payment)


# ── NemoGuard spend gate ────────────────────────────────────────────────────
# The spend gate runs before any money moves in close_dispute_window. A denial
# parks the pact at donation_declined (a clean terminal, no money) and records
# the guardrail's reason; an approval lets the existing donation path run.

from pact.spend_policy import GateDecision, SpendRequest  # noqa: E402


class FakeGate:
    """A SpendGate stub: records the request it saw and returns a fixed verdict."""

    def __init__(self, allowed: bool, reason: str = "test reason"):
        self._decision = GateDecision(allowed=allowed, reason=reason, rail="test")
        self.seen: SpendRequest | None = None

    def check(self, request: SpendRequest) -> GateDecision:
        self.seen = request
        return self._decision


def _failed_past_window(clock: FixedClock, settings):
    pact = _pact(clock, target=3)
    proofs = _passing_proofs(2, datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc))
    payment = SpyPaymentProvider()
    failed, _ = settle(pact, proofs, clock, payment, settings)
    clock.advance(hours=settings.dispute_grace_hours + 1)
    return failed, proofs, payment


def test_spend_gate_denial_blocks_donation_no_money_moves():
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    failed, proofs, payment = _failed_past_window(clock, settings)
    gate = FakeGate(allowed=False, reason="Spend blocked: exceeds the agent's $1.00 spend limit.")

    blocked, verdict = close_dispute_window(
        failed, proofs, clock, payment, settings, spend_gate=gate
    )

    assert payment.calls == 0  # provably no link-cli call
    assert blocked.status == PactStatus.donation_declined
    assert blocked.stake_state == StakeState.declined
    assert blocked.spend_request_id is None
    assert verdict.payment_action == PaymentAction.donation_declined
    # the guardrail saw the real proposed spend
    assert gate.seen is not None
    assert gate.seen.amount_cents == failed.stake_amount_cents
    assert gate.seen.charity_id == failed.charity_id
    assert gate.seen.verified_failure is True
    # the block reason is surfaced in the verdict for the UI + packet
    assert "spend blocked" in verdict.summary.lower()


def test_spend_gate_approval_lets_donation_fire():
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    failed, proofs, payment = _failed_past_window(clock, settings)
    gate = FakeGate(allowed=True)

    donated, verdict = close_dispute_window(
        failed, proofs, clock, payment, settings, spend_gate=gate
    )

    assert payment.calls == 1
    assert donated.status == PactStatus.donated
    assert donated.spend_request_id is not None
    assert verdict.payment_action == PaymentAction.donation_executed


def test_no_gate_preserves_existing_donation_behavior():
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    failed, proofs, payment = _failed_past_window(clock, settings)

    donated, verdict = close_dispute_window(failed, proofs, clock, payment, settings)

    assert payment.calls == 1
    assert donated.status == PactStatus.donated
    assert verdict.payment_action == PaymentAction.donation_executed

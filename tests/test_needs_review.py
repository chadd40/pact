from datetime import datetime, timedelta, timezone

import pytest

from pact.anticheat import TokenStore
from pact.clock import FixedClock
from pact.config import load_settings
from pact.lifecycle import close_dispute_window, settle, submit_proof
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


class RaisingProvider:
    """Reasoning provider whose resolve() always raises (resolver unavailable)."""

    def capabilities(self) -> set[str]:
        return {"text", "vision"}

    def resolve(self, task):
        raise RuntimeError("resolver boom")


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


def _proofs(passed: int, ambiguous: int, base: datetime) -> list[Proof]:
    """`passed` passed proofs then `ambiguous` ambiguous proofs, each on a distinct day."""
    out: list[Proof] = []
    day_i = 0
    for _ in range(passed):
        day = f"2026-06-{10 + day_i:02d}"
        out.append(_proof(day_i, day, ProofStatus.passed, base + timedelta(days=day_i)))
        day_i += 1
    for _ in range(ambiguous):
        day = f"2026-06-{10 + day_i:02d}"
        out.append(_proof(day_i, day, ProofStatus.ambiguous, base + timedelta(days=day_i)))
        day_i += 1
    return out


# ── (a) submit_proof: resolver error -> ambiguous proof, no crash ──────────────


def test_submit_proof_resolver_error_records_ambiguous_no_crash():
    clock = FixedClock(datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc))
    pact = _pact(clock, target=3)
    tokens = TokenStore()
    token = tokens.issue(pact.id, clock)

    proof = submit_proof(
        pact,
        Modality.text,
        token,
        True,
        None,  # no image -> no PIL, deterministic
        tokens,
        RaisingProvider(),
        clock,
        prior_phashes=None,
    )

    assert proof.status == ProofStatus.ambiguous
    assert proof.judge_reason == "judging unavailable (resolver error)"
    assert proof.token_ok is True  # token verification happened before the judge call


# ── (b) settle: ambiguous-decisive FAIL -> needs_review (no donation/window) ────


def test_settle_ambiguous_decisive_sets_needs_review_no_donation():
    # target 4, 3 passed + 1 ambiguous distinct day: 3 < 4 <= 3+1 -> flippable.
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    pact = _pact(clock, target=4)
    proofs = _proofs(3, 1, datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc))
    payment = SpyPaymentProvider()

    new_pact, verdict = settle(pact, proofs, clock, payment, settings)

    assert new_pact.status == PactStatus.needs_review
    assert payment.calls == 0  # never donates from needs_review
    assert new_pact.spend_request_id is None
    assert new_pact.stake_state == StakeState.committed  # stake untouched
    assert new_pact.dispute_window_closes_at is None  # no dispute window opened
    assert verdict.status == PactStatus.needs_review
    assert verdict.valid_proof_count == 3
    assert verdict.target_count == 4
    assert verdict.payment_action == PaymentAction.none
    assert verdict.payment_ref is None


def test_settle_ambiguous_not_decisive_is_clean_fail():
    # target 5, 3 passed + 1 ambiguous: 3 < 5 but 5 > 3+1 -> ambiguous can't flip it.
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    pact = _pact(clock, target=5)
    proofs = _proofs(3, 1, datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc))
    payment = SpyPaymentProvider()

    failed, verdict = settle(pact, proofs, clock, payment, settings)

    # Clean FAIL: window opens, no needs_review, no money yet.
    assert failed.status == PactStatus.failed
    assert failed.dispute_window_closes_at is not None
    assert payment.calls == 0
    assert verdict.status == PactStatus.failed
    assert verdict.payment_action == PaymentAction.none

    # And after the window closes it still donates exactly once (clean-FAIL unchanged).
    clock.advance(hours=settings.dispute_grace_hours + 1)
    donated, dverdict = close_dispute_window(failed, proofs, clock, payment, settings)
    assert donated.status == PactStatus.donated
    assert payment.calls == 1
    assert dverdict.payment_action == PaymentAction.donation_executed


def test_settle_needs_review_then_rejudged_proceeds_normally():
    # Re-settle after the ambiguous proof is re-judged: passed -> success; failed -> clean fail.
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    base = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
    payment = SpyPaymentProvider()

    pact = _pact(clock, target=4)
    proofs = _proofs(3, 1, base)
    paused, _ = settle(pact, proofs, clock, payment, settings)
    assert paused.status == PactStatus.needs_review

    # Ambiguous proof re-judged to passed -> now 4/4 -> success on re-settle.
    proofs[3].status = ProofStatus.passed
    resettled, verdict = settle(paused, proofs, clock, payment, settings)
    assert resettled.status == PactStatus.succeeded
    assert resettled.stake_state == StakeState.released
    assert payment.calls == 0
    assert verdict.status == PactStatus.succeeded
    assert verdict.valid_proof_count == 4

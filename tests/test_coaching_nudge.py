from datetime import datetime, timezone

from pact.clock import FixedClock
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
from pact.coaching import should_nudge


# ---- builders -------------------------------------------------------------

def _clock(day: int = 10) -> FixedClock:
    # Fixed instant: 2026-06-<day> 18:00 UTC
    return FixedClock(datetime(2026, 6, day, 18, 0, 0, tzinfo=timezone.utc))


def _rubric() -> Rubric:
    return Rubric(
        modality=Modality.photo,
        require_token=True,
        must_show=["clear evidence"],
        reject_if=["stock/watermark"],
        min_distinct_days=5,
        count_target=5,
    )


def _pact(
    *,
    status: PactStatus = PactStatus.active,
    deadline: datetime,
    target: int = 5,
) -> Pact:
    return Pact(
        id="pact_nudge01",
        owner="alice",
        original_prompt="work out 5x this week or $20 to charity",
        title="Commit: work out 5x",
        goal="Complete the committed action 5 times on 5 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=deadline,
        target_count=target,
        recommended_stake_cents=1000,
        stake_amount_cents=1000,
        charity_id="world_central_kitchen",
        charity_url="https://example.org/donate",
        rubric=_rubric(),
        status=status,
        stake_state=StakeState.committed,
        created_at=datetime(2026, 6, 8, 9, 0, 0, tzinfo=timezone.utc),
        started_at=datetime(2026, 6, 8, 9, 0, 0, tzinfo=timezone.utc),
    )


def _proof(*, day_bucket: str, received_at: datetime, status: ProofStatus = ProofStatus.passed) -> Proof:
    return Proof(
        id="proof_" + day_bucket,
        pact_id="pact_nudge01",
        modality=Modality.photo,
        received_at=received_at,
        day_bucket=day_bucket,
        token_ok=True,
        status=status,
        judge_checklist={"token": True, "content": True, "not_dup": True},
    )


def _outbound(*, sent_at: datetime, trigger: str = "mid_week") -> CoachingMessage:
    return CoachingMessage(
        id="cm_" + sent_at.isoformat(),
        pact_id="pact_nudge01",
        direction="outbound",
        trigger=trigger,
        body="nudge body",
        sent_at=sent_at,
    )


# ---- tests ----------------------------------------------------------------

def test_returns_none_when_not_active():
    clock = _clock(10)
    # deadline far out, no proofs -> would otherwise nudge, but status blocks it
    pact = _pact(status=PactStatus.succeeded, deadline=datetime(2026, 6, 20, 23, 59, tzinfo=timezone.utc))
    assert should_nudge(pact, [], [], clock) is None


def test_returns_none_when_outbound_already_sent_today():
    clock = _clock(10)
    pact = _pact(deadline=datetime(2026, 6, 20, 23, 59, tzinfo=timezone.utc))
    already = _outbound(sent_at=datetime(2026, 6, 10, 9, 0, 0, tzinfo=timezone.utc))
    assert should_nudge(pact, [], [already], clock) is None


def test_returns_none_when_proof_received_today():
    clock = _clock(10)
    # behind pace (0 valid, big target) but a proof landed today -> suppress
    pact = _pact(deadline=datetime(2026, 6, 11, 23, 59, tzinfo=timezone.utc), target=5)
    proof_today = _proof(
        day_bucket="2026-06-10",
        received_at=datetime(2026, 6, 10, 10, 0, 0, tzinfo=timezone.utc),
    )
    assert should_nudge(pact, [proof_today], [], clock) is None


def test_returns_behind_pace_when_not_on_pace():
    clock = _clock(10)
    # target 5, 0 valid, deadline tomorrow -> needed 5 > days_left 1 -> behind
    pact = _pact(deadline=datetime(2026, 6, 11, 23, 59, tzinfo=timezone.utc), target=5)
    assert should_nudge(pact, [], [], clock) == "behind_pace"


def test_returns_deadline_eve_when_on_pace_and_one_day_left():
    clock = _clock(10)
    # target 2, two valid distinct-day proofs (not today), deadline tomorrow
    # needed 0 <= days_left 1 -> on pace; days_left <= 1 -> deadline_eve
    pact = _pact(deadline=datetime(2026, 6, 11, 23, 59, tzinfo=timezone.utc), target=2)
    proofs = [
        _proof(day_bucket="2026-06-08", received_at=datetime(2026, 6, 8, 10, 0, tzinfo=timezone.utc)),
        _proof(day_bucket="2026-06-09", received_at=datetime(2026, 6, 9, 10, 0, tzinfo=timezone.utc)),
    ]
    assert should_nudge(pact, proofs, [], clock) == "deadline_eve"


def test_returns_mid_week_when_on_pace_and_many_days_left():
    clock = _clock(10)
    # target 5, 2 valid distinct days (not today), deadline 5 days out
    # needed 3 <= days_left 5 -> on pace; days_left > 1 -> mid_week
    pact = _pact(deadline=datetime(2026, 6, 15, 23, 59, tzinfo=timezone.utc), target=5)
    proofs = [
        _proof(day_bucket="2026-06-08", received_at=datetime(2026, 6, 8, 10, 0, tzinfo=timezone.utc)),
        _proof(day_bucket="2026-06-09", received_at=datetime(2026, 6, 9, 10, 0, tzinfo=timezone.utc)),
    ]
    assert should_nudge(pact, proofs, [], clock) == "mid_week"


def test_yesterdays_outbound_does_not_block_today():
    clock = _clock(10)
    pact = _pact(deadline=datetime(2026, 6, 11, 23, 59, tzinfo=timezone.utc), target=5)
    yesterday = _outbound(sent_at=datetime(2026, 6, 9, 9, 0, 0, tzinfo=timezone.utc))
    # nothing landed today, not on pace -> behind_pace despite yesterday's message
    assert should_nudge(pact, [], [yesterday], clock) == "behind_pace"

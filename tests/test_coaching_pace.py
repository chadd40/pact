from datetime import datetime, timedelta, timezone

from pact.clock import FixedClock
from pact.coaching import pace
from pact.models import (
    Modality,
    Pact,
    PactStatus,
    Proof,
    ProofStatus,
    Rubric,
    StakeState,
)


def _rubric() -> Rubric:
    return Rubric(
        modality=Modality.photo,
        must_show=["evidence of the activity"],
        min_distinct_days=5,
        count_target=5,
    )


def _pact(clock: FixedClock, *, target: int, deadline: datetime) -> Pact:
    now = clock.now()
    return Pact(
        id="pact_pace01",
        owner="colehaddad40@gmail.com",
        original_prompt="work out 5x this week or $20 to charity",
        title="Work out 5x this week",
        goal="Complete 5 workout sessions on 5 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=deadline,
        target_count=target,
        distinct_days=True,
        recommended_stake_cents=2000,
        stake_amount_cents=2000,
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
        pact_id="pact_pace01",
        modality=Modality.photo,
        received_at=received,
        day_bucket=day,
        token_issued="PACT-7Q",
        token_ok=True,
        status=status,
    )


def _two_passed(received: datetime) -> list[Proof]:
    # 2 distinct valid days; a 3rd passed proof reusing day-01 must NOT add a day,
    # and a failed proof on a fresh day must NOT count.
    return [
        _proof(1, "2026-01-01", ProofStatus.passed, received),
        _proof(2, "2026-01-02", ProofStatus.passed, received),
        _proof(3, "2026-01-01", ProofStatus.passed, received),
        _proof(4, "2026-01-03", ProofStatus.failed, received),
    ]


def test_two_of_five_three_days_left_on_pace():
    now = datetime(2026, 1, 4, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(now)
    pact = _pact(clock, target=5, deadline=now + timedelta(days=3))

    result = pace(pact, _two_passed(now), clock)

    assert result == {
        "valid": 2,
        "target": 5,
        "days_left": 3,
        "needed": 3,
        "on_pace": True,
    }


def test_two_of_five_one_day_left_off_pace():
    now = datetime(2026, 1, 4, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(now)
    pact = _pact(clock, target=5, deadline=now + timedelta(days=1))

    result = pace(pact, _two_passed(now), clock)

    assert result["valid"] == 2
    assert result["needed"] == 3
    assert result["days_left"] == 1
    assert result["on_pace"] is False


def test_days_left_never_negative_past_deadline():
    now = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(now)
    # Deadline is two days in the past.
    pact = _pact(clock, target=5, deadline=now - timedelta(days=2))

    result = pace(pact, _two_passed(now), clock)

    assert result["days_left"] == 0
    assert result["needed"] == 3
    assert result["on_pace"] is False

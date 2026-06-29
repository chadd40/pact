from datetime import datetime, timedelta, timezone

import pytest

from pact.clock import FixedClock
from pact.config import Settings
from pact.lifecycle import cancel, spend_freeze
from pact.models import Pact, PactStatus, Rubric, StakeState


def _rubric() -> Rubric:
    return Rubric(
        modality="photo",
        must_show=["dumbbell"],
        min_distinct_days=3,
        count_target=5,
    )


def _active_pact(*, started_at: datetime, deadline_at: datetime, clock: FixedClock) -> Pact:
    return Pact(
        id="pact_abc123",
        owner="owner@example.com",
        original_prompt="do the thing",
        title="Do the thing",
        goal="5 workouts",
        timezone="America/New_York",
        deadline_at=deadline_at,
        target_count=5,
        recommended_stake_cents=1000,
        stake_amount_cents=1000,
        charity_id="redcross",
        charity_url="https://www.redcross.org/donate",
        freezes_allowed=1,
        freezes_used=0,
        freeze_extension_hours=24,
        rubric=_rubric(),
        status=PactStatus.active,
        stake_state=StakeState.committed,
        created_at=clock.now(),
        started_at=started_at,
    )


def test_spend_freeze_moves_deadline_and_increments_used():
    start = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    clock = FixedClock(start)
    deadline = start + timedelta(days=2)
    pact = _active_pact(started_at=start, deadline_at=deadline, clock=clock)

    result = spend_freeze(pact, clock)

    assert result.freezes_used == 1
    assert result.deadline_at == deadline + timedelta(hours=24)
    assert result.status == PactStatus.active


def test_second_freeze_when_only_one_allowed_raises():
    start = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    clock = FixedClock(start)
    deadline = start + timedelta(days=2)
    pact = _active_pact(started_at=start, deadline_at=deadline, clock=clock)

    pact = spend_freeze(pact, clock)
    assert pact.freezes_used == 1

    with pytest.raises(Exception):
        spend_freeze(pact, clock)


def test_cancel_within_cooling_off_releases_no_donation():
    start = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    clock = FixedClock(start)
    deadline = start + timedelta(days=2)
    pact = _active_pact(started_at=start, deadline_at=deadline, clock=clock)
    settings = Settings()  # cooling_off_minutes default 60

    clock.advance(minutes=30)  # still inside the 60-minute window
    result = cancel(pact, clock, settings)

    assert result.status == PactStatus.canceled_release
    assert result.stake_state == StakeState.released


def test_cancel_after_cooling_off_forfeits_donation_pending():
    start = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    clock = FixedClock(start)
    deadline = start + timedelta(days=2)
    pact = _active_pact(started_at=start, deadline_at=deadline, clock=clock)
    settings = Settings()  # cooling_off_minutes default 60

    clock.advance(minutes=90)  # past the 60-minute window
    result = cancel(pact, clock, settings)

    assert result.status == PactStatus.donation_pending
    assert result.stake_state != StakeState.released


def test_cancel_draft_releases_without_crashing():
    # A draft has never started (started_at is None) and holds no committed stake;
    # the transition table allows draft -> canceled_release, so canceling one must
    # be a clean release rather than a crash (None + timedelta).
    start = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    clock = FixedClock(start)
    deadline = start + timedelta(days=2)
    pact = _active_pact(started_at=start, deadline_at=deadline, clock=clock)
    draft = pact.model_copy(
        update={
            "status": PactStatus.draft,
            "started_at": None,
            "stake_state": StakeState.none,
        }
    )
    settings = Settings()

    result = cancel(draft, clock, settings)

    assert result.status == PactStatus.canceled_release
    assert result.stake_state == StakeState.released

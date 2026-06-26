from datetime import datetime, timezone

import pytest

from pact.clock import FixedClock
from pact.lifecycle import (
    ALLOWED_TRANSITIONS,
    TransitionError,
    new_pact_id,
    transition,
)
from pact.models import Modality, Pact, PactStatus, Rubric, StakeState


def _make_pact(status: PactStatus = PactStatus.draft) -> Pact:
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc))
    rubric = Rubric(
        modality=Modality.photo,
        must_show=["person mid/post exercise"],
        min_distinct_days=5,
        count_target=5,
    )
    return Pact(
        id="pact_test01",
        owner="colehaddad40@gmail.com",
        original_prompt="work out 5x this week or $20 to charity",
        title="Work out 5x this week",
        goal="Complete 5 workout sessions on 5 distinct days this week.",
        timezone="America/Los_Angeles",
        deadline_at=datetime(2026, 6, 28, 23, 59, 59, tzinfo=timezone.utc),
        target_count=5,
        recommended_stake_cents=2000,
        stake_amount_cents=2000,
        charity_id="world_central_kitchen",
        charity_url="https://wck.org/donate",
        rubric=rubric,
        status=status,
        stake_state=StakeState.none,
        created_at=clock.now(),
    )


def test_draft_to_active_allowed():
    pact = _make_pact(PactStatus.draft)
    result = transition(pact, PactStatus.active)
    assert result.status == PactStatus.active
    assert result is pact


def test_active_to_succeeded_allowed():
    pact = _make_pact(PactStatus.active)
    result = transition(pact, PactStatus.evaluating)
    assert result.status == PactStatus.evaluating
    result = transition(result, PactStatus.succeeded)
    assert result.status == PactStatus.succeeded


def test_succeeded_to_active_raises():
    pact = _make_pact(PactStatus.succeeded)
    with pytest.raises(TransitionError):
        transition(pact, PactStatus.active)


def test_allowed_transitions_is_keyed_by_status():
    assert PactStatus.active in ALLOWED_TRANSITIONS[PactStatus.draft]
    assert PactStatus.succeeded in ALLOWED_TRANSITIONS[PactStatus.evaluating]
    assert ALLOWED_TRANSITIONS[PactStatus.succeeded] == set()


def test_new_pact_id_deterministic_for_seed():
    first = new_pact_id("work out 5x this week")
    second = new_pact_id("work out 5x this week")
    assert first == second
    assert first.startswith("pact_")
    assert len(first) == len("pact_") + 6


def test_new_pact_id_differs_by_seed():
    assert new_pact_id("seed-a") != new_pact_id("seed-b")

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
        owner="demo@pact.local",
        original_prompt="work out 5x this week or $20 to charity",
        title="Work out 5x this week",
        goal="Complete 5 workout sessions on 5 distinct days this week.",
        timezone="America/Los_Angeles",
        deadline_at=datetime(2026, 6, 28, 23, 59, 59, tzinfo=timezone.utc),
        target_count=5,
        recommended_stake_cents=2000,
        stake_amount_cents=2000,
        charity_id="against_malaria_foundation",
        charity_url="https://againstmalaria.com/donate",
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


def test_pre_authorize_creation_transitions_exist():
    # Stake is pre-authorized at creation: draft -> awaiting_stake -> active.
    assert PactStatus.awaiting_stake in ALLOWED_TRANSITIONS[PactStatus.draft]
    assert PactStatus.active in ALLOWED_TRANSITIONS[PactStatus.awaiting_stake]
    # Abandoning the Link approval releases (no charge).
    assert PactStatus.canceled_release in ALLOWED_TRANSITIONS[PactStatus.awaiting_stake]


def test_donated_to_donation_complete_allowed():
    # Link-confirmed charge resolves the donation.
    pact = _make_pact(PactStatus.donated)
    result = transition(pact, PactStatus.donation_complete)
    assert result.status == PactStatus.donation_complete
    assert ALLOWED_TRANSITIONS[PactStatus.donation_complete] == set()


def test_active_to_donation_complete_raises():
    pact = _make_pact(PactStatus.active)
    with pytest.raises(TransitionError):
        transition(pact, PactStatus.donation_complete)


def test_pact_carries_stake_approval_url_field():
    pact = _make_pact(PactStatus.awaiting_stake)
    pact.stake_approval_url = "https://link.example/approve/abc"
    assert pact.stake_approval_url == "https://link.example/approve/abc"


def test_new_pact_id_deterministic_for_seed():
    first = new_pact_id("work out 5x this week")
    second = new_pact_id("work out 5x this week")
    assert first == second
    assert first.startswith("pact_")
    assert len(first) == len("pact_") + 6


def test_new_pact_id_differs_by_seed():
    assert new_pact_id("seed-a") != new_pact_id("seed-b")

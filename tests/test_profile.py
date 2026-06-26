from datetime import datetime, timezone

from pact.clock import FixedClock
from pact.models import Modality, Pact, PactStatus, Profile, Rubric
from pact.profile import record_outcome


def _clock(dt: datetime | None = None) -> FixedClock:
    return FixedClock(dt or datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc))


def _rubric() -> Rubric:
    return Rubric(
        modality=Modality.photo,
        must_show=["person mid/post exercise"],
        min_distinct_days=5,
        count_target=5,
    )


def _pact(pact_id: str, status: PactStatus, *, title: str = "Work out 5x") -> Pact:
    created = datetime(2026, 6, 20, 9, 0, 0, tzinfo=timezone.utc)
    return Pact(
        id=pact_id,
        owner="colehaddad40@gmail.com",
        original_prompt="work out 5x this week or $20 to charity",
        title=title,
        goal="Complete 5 workout sessions on 5 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=datetime(2026, 6, 27, 9, 0, 0, tzinfo=timezone.utc),
        target_count=5,
        recommended_stake_cents=2000,
        stake_amount_cents=2000,
        charity_id="world_central_kitchen",
        charity_url="https://wck.org/donate",
        rubric=_rubric(),
        status=status,
        created_at=created,
    )


def _empty_profile() -> Profile:
    return Profile(owner="colehaddad40@gmail.com")


def test_success_increments_current_best_streak_and_kept():
    profile = _empty_profile()
    clock = _clock()
    pact = _pact("pact_win01", PactStatus.succeeded)

    updated = record_outcome(profile, pact, clock)

    assert updated.current_streak == 1
    assert updated.best_streak == 1
    assert updated.kept == 1
    assert updated.failed == 0
    assert updated.pact_ids == ["pact_win01"]


def test_two_successes_extend_streak_and_best():
    profile = _empty_profile()
    clock = _clock()

    profile = record_outcome(profile, _pact("pact_a", PactStatus.succeeded), clock)
    profile = record_outcome(profile, _pact("pact_b", PactStatus.succeeded), clock)

    assert profile.current_streak == 2
    assert profile.best_streak == 2
    assert profile.kept == 2
    assert profile.failed == 0


def test_failure_resets_current_streak_and_increments_failed():
    profile = _empty_profile()
    clock = _clock()

    profile = record_outcome(profile, _pact("pact_a", PactStatus.succeeded), clock)
    profile = record_outcome(profile, _pact("pact_b", PactStatus.succeeded), clock)
    assert profile.current_streak == 2
    assert profile.best_streak == 2

    profile = record_outcome(profile, _pact("pact_c", PactStatus.donated), clock)

    assert profile.current_streak == 0
    assert profile.failed == 1
    assert profile.kept == 2
    # best_streak is the max ever seen and survives the reset.
    assert profile.best_streak == 2


def test_best_streak_is_the_max_seen_across_resets():
    profile = _empty_profile()
    clock = _clock()

    # Run of 3.
    profile = record_outcome(profile, _pact("pact_a", PactStatus.succeeded), clock)
    profile = record_outcome(profile, _pact("pact_b", PactStatus.succeeded), clock)
    profile = record_outcome(profile, _pact("pact_c", PactStatus.succeeded), clock)
    # Break it.
    profile = record_outcome(profile, _pact("pact_d", PactStatus.failed), clock)
    # New run of 1 (shorter than the prior best).
    profile = record_outcome(profile, _pact("pact_e", PactStatus.succeeded), clock)

    assert profile.current_streak == 1
    assert profile.best_streak == 3
    assert profile.kept == 4
    assert profile.failed == 1


def test_history_entry_appended_with_correct_outcome():
    profile = _empty_profile()
    ended = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = _clock(ended)

    profile = record_outcome(
        profile, _pact("pact_win01", PactStatus.succeeded, title="Run daily"), clock
    )
    profile = record_outcome(
        profile, _pact("pact_fail01", PactStatus.donation_failed, title="Read nightly"), clock
    )

    assert profile.history == [
        {
            "pact_id": "pact_win01",
            "title": "Run daily",
            "outcome": "succeeded",
            "ended_at": ended.isoformat(),
        },
        {
            "pact_id": "pact_fail01",
            "title": "Read nightly",
            "outcome": "failed",
            "ended_at": ended.isoformat(),
        },
    ]


def test_all_failure_statuses_count_as_failure():
    clock = _clock()
    for status in (
        PactStatus.failed,
        PactStatus.donated,
        PactStatus.donation_failed,
        PactStatus.donation_declined,
        PactStatus.canceled_forfeit,
    ):
        profile = record_outcome(_empty_profile(), _pact("pact_x", status), clock)
        assert profile.failed == 1, status
        assert profile.kept == 0, status
        assert profile.current_streak == 0, status
        assert profile.history[0]["outcome"] == "failed", status


def test_idempotent_does_not_double_count_same_terminal_pact():
    profile = _empty_profile()
    clock = _clock()
    pact = _pact("pact_win01", PactStatus.succeeded)

    once = record_outcome(profile, pact, clock)
    twice = record_outcome(once, pact, clock)

    assert twice.current_streak == 1
    assert twice.best_streak == 1
    assert twice.kept == 1
    assert twice.failed == 0
    assert twice.pact_ids == ["pact_win01"]
    assert len(twice.history) == 1


def test_pact_id_not_duplicated_when_already_present():
    profile = Profile(owner="colehaddad40@gmail.com", pact_ids=["pact_win01"])
    clock = _clock()
    pact = _pact("pact_win01", PactStatus.succeeded)

    updated = record_outcome(profile, pact, clock)

    assert updated.pact_ids == ["pact_win01"]
    assert updated.kept == 1
    assert len(updated.history) == 1

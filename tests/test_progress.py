from datetime import datetime, timezone

from pact.models import Modality, Pact, PactStatus, Proof, ProofStatus, Rubric, StakeState
from pact.progress import compute_progress


def _pact() -> Pact:
    return Pact(
        id="pact_p",
        owner="a@b.com",
        original_prompt="x",
        title="t",
        goal="g",
        timezone="America/Los_Angeles",
        created_at=datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc),
        started_at=datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc),
        deadline_at=datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),  # 7-day window
        target_count=5,
        distinct_days=True,
        recommended_stake_cents=2000,
        stake_amount_cents=2000,
        charity_id="against_malaria_foundation",
        charity_url="https://againstmalaria.com/donate",
        rubric=Rubric(modality=Modality.photo, must_show=["x"], min_distinct_days=5, count_target=5),
        status=PactStatus.active,
        stake_state=StakeState.committed,
    )


def _passed(idx: int, day: str) -> Proof:
    return Proof(
        id=f"proof_{idx}",
        pact_id="pact_p",
        modality=Modality.photo,
        received_at=datetime.fromisoformat(f"{day}T12:00:00+00:00"),
        day_bucket=day,
        token_ok=True,
        status=ProofStatus.passed,
    )


def test_progress_midway_on_track():
    pact = _pact()
    proofs = [_passed(0, "2026-06-20"), _passed(1, "2026-06-21"), _passed(2, "2026-06-22")]
    now = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)  # 3 of 7 days elapsed

    prog = compute_progress(pact, proofs, now)

    assert prog == {
        "valid_count": 3,
        "target": 5,
        "pct": 60,
        "days_left": 4,
        "on_track": True,   # 3 >= 5 * (3/7) = 2.14
        "behind": False,
        "milestone": 50,    # highest crossed of 25/50/75/100
    }


def test_progress_behind_pace_near_deadline():
    pact = _pact()
    proofs = [_passed(0, "2026-06-20")]  # only 1 of 5
    now = datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc)  # 6 of 7 days elapsed

    prog = compute_progress(pact, proofs, now)

    assert prog["valid_count"] == 1
    assert prog["pct"] == 20
    assert prog["days_left"] == 1
    assert prog["on_track"] is False  # 1 < 5 * (6/7) = 4.28
    assert prog["behind"] is True
    assert prog["milestone"] == 0


def test_progress_complete_is_capped_and_not_behind():
    pact = _pact()
    proofs = [_passed(i, f"2026-06-2{i}") for i in range(5)]  # 5 distinct days
    now = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)

    prog = compute_progress(pact, proofs, now)

    assert prog["valid_count"] == 5
    assert prog["pct"] == 100
    assert prog["on_track"] is True
    assert prog["behind"] is False
    assert prog["milestone"] == 100


def test_progress_past_deadline_has_zero_days_left():
    pact = _pact()
    now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    prog = compute_progress(pact, [], now)
    assert prog["days_left"] == 0
    assert prog["pct"] == 0
    assert prog["milestone"] == 0

from datetime import datetime, timezone

import pytest

from pact.models import (
    CoachingMessage,
    Modality,
    Pact,
    PactStatus,
    Profile,
    Proof,
    ProofStatus,
    ReasoningTask,
    Rubric,
    TaskType,
    Verdict,
    PaymentAction,
)
from pact.repository import Repository

UTC = timezone.utc


@pytest.fixture
def repo() -> Repository:
    r = Repository.connect(":memory:")
    r.init_schema()
    return r


def make_rubric() -> Rubric:
    return Rubric(
        modality=Modality.photo,
        must_show=["person mid/post exercise"],
        min_distinct_days=5,
        count_target=5,
    )


def make_pact(pact_id: str = "pact_abc123") -> Pact:
    return Pact(
        id=pact_id,
        owner="colehaddad40@gmail.com",
        original_prompt="work out 5x this week or $20 to charity",
        title="Work out 5x this week",
        goal="Complete 5 workout sessions on 5 distinct days this week.",
        timezone="America/Los_Angeles",
        deadline_at=datetime(2026, 6, 28, 23, 59, 59, tzinfo=UTC),
        target_count=5,
        recommended_stake_cents=2000,
        stake_amount_cents=2000,
        charity_id="against_malaria_foundation",
        charity_url="https://againstmalaria.com/donate",
        rubric=make_rubric(),
        status=PactStatus.active,
        created_at=datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC),
    )


def make_proof(proof_id: str = "proof_1", pact_id: str = "pact_abc123") -> Proof:
    return Proof(
        id=proof_id,
        pact_id=pact_id,
        modality=Modality.photo,
        received_at=datetime(2026, 6, 24, 18, 3, 0, tzinfo=UTC),
        day_bucket="2026-06-24",
        token_issued="PACT-7Q",
        token_ok=True,
        status=ProofStatus.passed,
    )


def make_task(task_id: str = "task_1") -> ReasoningTask:
    return ReasoningTask(
        id=task_id,
        pact_id="pact_abc123",
        type=TaskType.judge_proof,
        required_capability="vision",
        input={"content_ok": True},
        created_at=datetime(2026, 6, 24, 18, 4, 0, tzinfo=UTC),
    )


def make_verdict(pact_id: str = "pact_abc123") -> Verdict:
    return Verdict(
        pact_id=pact_id,
        status=PactStatus.failed,
        valid_proof_count=4,
        target_count=5,
        freezes_used=0,
        summary="4 of 5 distinct-day proofs by deadline.",
        proof_ids=["proof_1"],
        payment_action=PaymentAction.donation_executed,
        honesty_note="Commitment device; proofs judged best-effort.",
    )


def make_msg(
    msg_id: str,
    pact_id: str,
    direction: str,
    trigger: str,
    body: str,
    sent_at: datetime,
) -> CoachingMessage:
    return CoachingMessage(
        id=msg_id,
        pact_id=pact_id,
        direction=direction,
        trigger=trigger,
        pact_state_snapshot={"valid": 2, "target": 5, "days_left": 3},
        channel="web",
        body=body,
        sent_at=sent_at,
    )


def test_save_and_get_profile_round_trips(repo: Repository) -> None:
    profile = Profile(
        owner="colehaddad40@gmail.com",
        pact_ids=["pact_abc123"],
        current_streak=2,
        best_streak=4,
        kept=4,
        failed=1,
        history=[
            {
                "pact_id": "pact_abc123",
                "title": "Work out 5x this week",
                "outcome": "succeeded",
                "ended_at": "2026-06-28T23:59:59+00:00",
            }
        ],
    )
    repo.save_profile(profile)
    loaded = repo.get_profile("colehaddad40@gmail.com")
    assert loaded is not None
    assert loaded == profile
    assert loaded.current_streak == 2
    assert loaded.best_streak == 4
    assert loaded.history[0]["outcome"] == "succeeded"


def test_get_profile_missing_returns_none(repo: Repository) -> None:
    assert repo.get_profile("nobody@example.com") is None


def test_save_profile_overwrites_by_owner(repo: Repository) -> None:
    repo.save_profile(Profile(owner="cole@example.com", current_streak=1))
    repo.save_profile(Profile(owner="cole@example.com", current_streak=3, kept=3))
    loaded = repo.get_profile("cole@example.com")
    assert loaded is not None
    assert loaded.current_streak == 3
    assert loaded.kept == 3


def test_coaching_messages_return_in_sent_at_order(repo: Repository) -> None:
    first = make_msg(
        "cm_1", "pact_abc123", "outbound", "mid_week", "Halfway there!",
        datetime(2026, 6, 25, 9, 0, 0, tzinfo=UTC),
    )
    second = make_msg(
        "cm_2", "pact_abc123", "inbound", "reply", "On it.",
        datetime(2026, 6, 25, 14, 30, 0, tzinfo=UTC),
    )
    third = make_msg(
        "cm_3", "pact_abc123", "outbound", "deadline_eve", "One day left.",
        datetime(2026, 6, 27, 8, 0, 0, tzinfo=UTC),
    )
    other = make_msg(
        "cm_x", "pact_other", "outbound", "kickoff", "Different pact.",
        datetime(2026, 6, 25, 10, 0, 0, tzinfo=UTC),
    )
    # Save out of chronological order to prove ORDER BY works.
    repo.save_coaching_message(third)
    repo.save_coaching_message(first)
    repo.save_coaching_message(other)
    repo.save_coaching_message(second)

    msgs = repo.list_coaching_messages("pact_abc123")
    assert [m.id for m in msgs] == ["cm_1", "cm_2", "cm_3"]
    assert all(m.pact_id == "pact_abc123" for m in msgs)
    assert msgs[0].body == "Halfway there!"
    assert msgs[1].direction == "inbound"
    assert msgs[0].pact_state_snapshot == {"valid": 2, "target": 5, "days_left": 3}


def test_list_coaching_messages_empty_returns_empty(repo: Repository) -> None:
    assert repo.list_coaching_messages("pact_none") == []


def test_save_coaching_message_overwrites_by_id(repo: Repository) -> None:
    original = make_msg(
        "cm_1", "pact_abc123", "outbound", "mid_week", "v1",
        datetime(2026, 6, 25, 9, 0, 0, tzinfo=UTC),
    )
    repo.save_coaching_message(original)
    repo.save_coaching_message(original.model_copy(update={"body": "v2"}))
    msgs = repo.list_coaching_messages("pact_abc123")
    assert len(msgs) == 1
    assert msgs[0].body == "v2"


def test_reset_all_empties_every_table(repo: Repository) -> None:
    repo.save_pact(make_pact())
    repo.save_proof(make_proof())
    repo.save_task(make_task())
    repo.save_verdict(make_verdict())
    repo.save_profile(Profile(owner="colehaddad40@gmail.com", pact_ids=["pact_abc123"]))
    repo.save_coaching_message(
        make_msg(
            "cm_1", "pact_abc123", "outbound", "mid_week", "hi",
            datetime(2026, 6, 25, 9, 0, 0, tzinfo=UTC),
        )
    )

    # Sanity: rows exist before reset.
    assert repo.get_pact("pact_abc123") is not None
    assert repo.list_proofs("pact_abc123") != []
    assert repo.get_task("task_1") is not None
    assert repo.get_verdict("pact_abc123") is not None
    assert repo.get_profile("colehaddad40@gmail.com") is not None
    assert repo.list_coaching_messages("pact_abc123") != []

    repo.reset_all()

    assert repo.get_pact("pact_abc123") is None
    assert repo.list_pacts() == []
    assert repo.list_proofs("pact_abc123") == []
    assert repo.get_task("task_1") is None
    assert repo.pending_tasks() == []
    assert repo.get_verdict("pact_abc123") is None
    assert repo.get_profile("colehaddad40@gmail.com") is None
    assert repo.list_coaching_messages("pact_abc123") == []


def test_reset_all_on_empty_db_is_safe(repo: Repository) -> None:
    repo.reset_all()
    assert repo.list_pacts() == []

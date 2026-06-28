from datetime import datetime, timedelta, timezone

import pytest

from pact.models import (
    AgentSession,
    Modality,
    Pact,
    PactStatus,
    PaymentAttempt,
    Proof,
    ProofReview,
    ProofStatus,
    ReasoningTask,
    Rubric,
    StakeState,
    TaskStatus,
    TaskType,
    Verdict,
    PaymentAction,
)
from pact.repository import Repository

UTC = timezone.utc


def make_rubric() -> Rubric:
    return Rubric(
        modality=Modality.photo,
        must_show=["person mid/post exercise"],
        min_distinct_days=5,
        count_target=5,
    )


def make_pact(
    pact_id: str = "pact_abc123",
    owner: str = "demo@pact.local",
    status: PactStatus = PactStatus.draft,
    deadline_at: datetime | None = None,
) -> Pact:
    deadline = deadline_at or datetime(2026, 6, 28, 23, 59, 59, tzinfo=UTC)
    return Pact(
        id=pact_id,
        owner=owner,
        original_prompt="work out 5x this week or $20 to charity",
        title="Work out 5x this week",
        goal="Complete 5 workout sessions on 5 distinct days this week.",
        timezone="America/Los_Angeles",
        deadline_at=deadline,
        target_count=5,
        recommended_stake_cents=2000,
        stake_amount_cents=2000,
        charity_id="against_malaria_foundation",
        charity_url="https://againstmalaria.com/donate",
        rubric=make_rubric(),
        status=status,
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
        judge_reason="Token visible; person on treadmill.",
        judge_checklist={"token": True, "content": True, "not_dup": True},
    )


def make_task(task_id: str = "task_1", pact_id: str | None = "pact_abc123") -> ReasoningTask:
    return ReasoningTask(
        id=task_id,
        pact_id=pact_id,
        type=TaskType.judge_proof,
        required_capability="vision",
        input={"token_ok": True, "is_duplicate": False, "content_ok": True, "rubric": {}},
        created_at=datetime(2026, 6, 24, 18, 4, 0, tzinfo=UTC),
    )


def make_verdict(pact_id: str = "pact_abc123") -> Verdict:
    return Verdict(
        pact_id=pact_id,
        status=PactStatus.failed,
        valid_proof_count=4,
        target_count=5,
        freezes_used=0,
        summary="4 of 5 distinct-day proofs by deadline. Pact failed.",
        proof_ids=["proof_1", "proof_2"],
        payment_action=PaymentAction.donation_executed,
        honesty_note="Commitment device; proofs judged best-effort, not forensically verified.",
    )


@pytest.fixture
def repo() -> Repository:
    r = Repository.connect(":memory:")
    r.init_schema()
    return r


def test_save_and_get_pact_round_trips(repo: Repository) -> None:
    pact = make_pact()
    repo.save_pact(pact)
    loaded = repo.get_pact(pact.id)
    assert loaded is not None
    assert loaded == pact
    assert loaded.rubric.count_target == 5
    assert loaded.deadline_at == pact.deadline_at
    assert loaded.deadline_at.tzinfo is not None


def test_get_pact_missing_returns_none(repo: Repository) -> None:
    assert repo.get_pact("pact_nope") is None


def test_update_pact_overwrites(repo: Repository) -> None:
    pact = make_pact(status=PactStatus.draft)
    repo.save_pact(pact)
    updated = pact.model_copy(update={"status": PactStatus.active, "stake_state": StakeState.committed})
    repo.update_pact(updated)
    loaded = repo.get_pact(pact.id)
    assert loaded is not None
    assert loaded.status == PactStatus.active
    assert loaded.stake_state == StakeState.committed


def test_list_pacts_filters_by_owner(repo: Repository) -> None:
    repo.save_pact(make_pact(pact_id="pact_a", owner="alice@example.com"))
    repo.save_pact(make_pact(pact_id="pact_b", owner="bob@example.com"))
    repo.save_pact(make_pact(pact_id="pact_c", owner="alice@example.com"))
    alice = repo.list_pacts(owner="alice@example.com")
    assert {p.id for p in alice} == {"pact_a", "pact_c"}
    everyone = repo.list_pacts()
    assert {p.id for p in everyone} == {"pact_a", "pact_b", "pact_c"}


def test_due_active_pacts_only_active_past_deadline(repo: Repository) -> None:
    now = datetime(2026, 6, 28, 0, 0, 0, tzinfo=UTC)
    past = now - timedelta(hours=1)
    future = now + timedelta(hours=1)
    repo.save_pact(make_pact(pact_id="due_active", status=PactStatus.active, deadline_at=past))
    repo.save_pact(make_pact(pact_id="not_due_active", status=PactStatus.active, deadline_at=future))
    repo.save_pact(make_pact(pact_id="past_but_draft", status=PactStatus.draft, deadline_at=past))
    repo.save_pact(make_pact(pact_id="past_but_succeeded", status=PactStatus.succeeded, deadline_at=past))
    due = repo.due_active_pacts(now)
    assert {p.id for p in due} == {"due_active"}


def test_due_active_pacts_includes_exact_deadline(repo: Repository) -> None:
    now = datetime(2026, 6, 28, 0, 0, 0, tzinfo=UTC)
    repo.save_pact(make_pact(pact_id="exact", status=PactStatus.active, deadline_at=now))
    due = repo.due_active_pacts(now)
    assert {p.id for p in due} == {"exact"}


def test_proof_save_and_list(repo: Repository) -> None:
    repo.save_proof(make_proof(proof_id="proof_1", pact_id="pact_abc123"))
    repo.save_proof(make_proof(proof_id="proof_2", pact_id="pact_abc123"))
    repo.save_proof(make_proof(proof_id="proof_x", pact_id="pact_other"))
    proofs = repo.list_proofs("pact_abc123")
    assert {p.id for p in proofs} == {"proof_1", "proof_2"}
    assert all(p.pact_id == "pact_abc123" for p in proofs)
    one = next(p for p in proofs if p.id == "proof_1")
    assert one.judge_checklist == {"token": True, "content": True, "not_dup": True}


def test_task_save_get_update_and_pending(repo: Repository) -> None:
    task = make_task(task_id="task_1")
    repo.save_task(task)
    loaded = repo.get_task("task_1")
    assert loaded is not None
    assert loaded == task
    assert repo.get_task("task_missing") is None

    pending = repo.pending_tasks()
    assert {t.id for t in pending} == {"task_1"}
    pending_vision = repo.pending_tasks(capability="vision")
    assert {t.id for t in pending_vision} == {"task_1"}
    pending_text = repo.pending_tasks(capability="text")
    assert pending_text == []

    done = task.model_copy(
        update={"status": TaskStatus.done, "result": {"status": "failed"}, "claimed_by": "agent_1"}
    )
    repo.update_task(done)
    reloaded = repo.get_task("task_1")
    assert reloaded is not None
    assert reloaded.status == TaskStatus.done
    assert reloaded.result == {"status": "failed"}
    assert repo.pending_tasks() == []


def test_verdict_save_and_get(repo: Repository) -> None:
    repo.save_verdict(make_verdict())
    loaded = repo.get_verdict("pact_abc123")
    assert loaded is not None
    assert loaded == make_verdict()
    assert loaded.payment_action == PaymentAction.donation_executed
    assert repo.get_verdict("pact_none") is None


def test_payment_attempt_save_get_and_list(repo: Repository) -> None:
    created = datetime(2026, 6, 26, 12, 0, 0, tzinfo=UTC)
    attempt = PaymentAttempt(
        id="pay_1",
        pact_id="pact_abc123",
        owner="alice@example.com",
        provider="link_cli",
        mode="dry_run",
        status="created",
        amount_cents=2000,
        currency="usd",
        charity_id="against_malaria_foundation",
        merchant_name="Against Malaria Foundation",
        merchant_url="https://www.againstmalaria.com/donation.aspx",
        idempotency_key="pact_abc123:donation",
        created_at=created,
        updated_at=created,
    )
    repo.save_payment_attempt(attempt)

    loaded = repo.get_payment_attempt("pay_1")
    assert loaded == attempt
    assert repo.list_payment_attempts("pact_abc123") == [attempt]
    assert repo.list_payment_attempts("pact_other") == []


def test_proof_review_save_get_and_list(repo: Repository) -> None:
    review = ProofReview(
        id="review_1",
        proof_id="proof_1",
        pact_id="pact_abc123",
        reviewer="Hermes",
        capabilities=["vision"],
        input_artifacts={"image_path": "artifacts/pact_abc123/proof_1.png"},
        status=ProofStatus.passed,
        reason="Token visible and goal evidence clear.",
        checklist={"token_visible": True, "goal_visible": True},
        created_at=datetime(2026, 6, 26, 12, 0, 0, tzinfo=UTC),
    )
    repo.save_proof_review(review)

    assert repo.get_proof_review("review_1") == review
    assert repo.list_proof_reviews("proof_1") == [review]
    assert repo.list_proof_reviews("proof_other") == []


def test_agent_session_save_get_resolve_and_revoke(repo: Repository) -> None:
    session = AgentSession(
        owner="alice@example.com",
        token_hash="hash_abc",
        token_prefix="pat_abc",
        created_at=datetime(2026, 6, 26, 12, 0, 0, tzinfo=UTC),
        expires_at=datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC),
        scopes=["claim_tasks", "post_results"],
    )
    repo.save_agent_session(session)

    assert repo.get_agent_session("alice@example.com") == session
    assert repo.owner_for_token_hash("hash_abc") == "alice@example.com"

    revoked = session.model_copy(update={"revoked_at": datetime(2026, 6, 27, 12, 0, 0, tzinfo=UTC)})
    repo.save_agent_session(revoked)
    assert repo.get_agent_session("alice@example.com").revoked_at == revoked.revoked_at
    assert repo.owner_for_token_hash("hash_abc") is None


def test_save_verdict_replaces_existing(repo: Repository) -> None:
    repo.save_verdict(make_verdict())
    updated = make_verdict().model_copy(update={"status": PactStatus.succeeded, "valid_proof_count": 5})
    repo.save_verdict(updated)
    loaded = repo.get_verdict("pact_abc123")
    assert loaded is not None
    assert loaded.status == PactStatus.succeeded
    assert loaded.valid_proof_count == 5

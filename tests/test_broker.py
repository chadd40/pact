from datetime import datetime, timezone

import pytest

from pact.broker import (
    BrokerError,
    claim,
    enqueue,
    get_result,
    pending_for,
    post_result,
)
from pact.clock import FixedClock
from pact.models import TaskStatus, TaskType
from pact.repository import Repository

UTC = timezone.utc
FIXED = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)


def _clock() -> FixedClock:
    return FixedClock(FIXED)


@pytest.fixture
def repo() -> Repository:
    r = Repository.connect(":memory:")
    r.init_schema()
    return r


def test_enqueue_creates_a_pending_task(repo: Repository) -> None:
    task = enqueue(
        repo,
        TaskType.judge_proof,
        "pact_abc123",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        _clock(),
        required_capability="vision",
    )
    assert task.type == TaskType.judge_proof
    assert task.pact_id == "pact_abc123"
    assert task.required_capability == "vision"
    assert task.status == TaskStatus.pending
    assert task.result is None
    assert task.claimed_by is None
    assert task.created_at == FIXED
    # Persisted under its id.
    stored = repo.get_task(task.id)
    assert stored is not None
    assert stored == task


def test_enqueue_allows_no_pact_and_defaults_capability_none(repo: Repository) -> None:
    task = enqueue(repo, TaskType.draft, None, {"prompt": "run 5x"}, _clock())
    assert task.pact_id is None
    assert task.required_capability is None
    assert repo.get_task(task.id) is not None


def test_pending_for_filters_by_capability(repo: Repository) -> None:
    vision = enqueue(
        repo, TaskType.judge_proof, "p1", {"token_ok": True}, _clock(),
        required_capability="vision",
    )
    text = enqueue(
        repo, TaskType.coach, "p2", {"valid": 1, "target": 5}, _clock(),
        required_capability="text",
    )
    anycap = enqueue(repo, TaskType.draft, None, {"prompt": "x"}, _clock())

    all_ids = {t.id for t in pending_for(repo)}
    assert all_ids == {vision.id, text.id, anycap.id}

    assert {t.id for t in pending_for(repo, capability="vision")} == {vision.id}
    assert {t.id for t in pending_for(repo, capability="text")} == {text.id}
    assert pending_for(repo, capability="audio") == []


def test_claim_sets_claimed_and_claimed_by(repo: Repository) -> None:
    task = enqueue(
        repo, TaskType.judge_proof, "p1", {"token_ok": True}, _clock(),
        required_capability="vision",
    )
    claimed = claim(repo, task.id, "worker_1", {"text", "vision"})
    assert claimed.status == TaskStatus.claimed
    assert claimed.claimed_by == "worker_1"
    # Persisted, and no longer pending.
    assert repo.get_task(task.id).status == TaskStatus.claimed
    assert pending_for(repo) == []


def test_claim_missing_task_raises_keyerror(repo: Repository) -> None:
    with pytest.raises(KeyError):
        claim(repo, "task_missing", "worker_1", {"text", "vision"})


def test_claim_twice_rejects_second_claim(repo: Repository) -> None:
    task = enqueue(repo, TaskType.draft, None, {"prompt": "x"}, _clock())
    claim(repo, task.id, "worker_1", {"text", "vision"})
    with pytest.raises(BrokerError):
        claim(repo, task.id, "worker_2", {"text", "vision"})
    # Original claimant is unchanged.
    assert repo.get_task(task.id).claimed_by == "worker_1"


def test_claim_capability_mismatch_rejected(repo: Repository) -> None:
    task = enqueue(
        repo, TaskType.judge_proof, "p1", {"token_ok": True}, _clock(),
        required_capability="vision",
    )
    with pytest.raises(BrokerError):
        claim(repo, task.id, "worker_text_only", {"text"})
    # Task stays pending and unclaimed so another worker can take it.
    assert repo.get_task(task.id).status == TaskStatus.pending
    assert repo.get_task(task.id).claimed_by is None


def test_claim_with_no_required_capability_accepts_any_worker(repo: Repository) -> None:
    task = enqueue(repo, TaskType.draft, None, {"prompt": "x"}, _clock())
    claimed = claim(repo, task.id, "worker_text_only", {"text"})
    assert claimed.status == TaskStatus.claimed
    assert claimed.claimed_by == "worker_text_only"


def test_post_result_sets_done_and_result(repo: Repository) -> None:
    task = enqueue(
        repo, TaskType.judge_proof, "p1", {"token_ok": True}, _clock(),
        required_capability="vision",
    )
    claim(repo, task.id, "worker_1", {"text", "vision"})
    result = {"status": "passed", "reason": "looks good", "checklist": {"token": True}}
    done = post_result(repo, task.id, result)
    assert done.status == TaskStatus.done
    assert done.result == result
    assert repo.get_task(task.id).result == result


def test_post_result_missing_task_raises_keyerror(repo: Repository) -> None:
    with pytest.raises(KeyError):
        post_result(repo, "task_missing", {"status": "passed"})


def test_post_result_requires_claim_first(repo: Repository) -> None:
    task = enqueue(repo, TaskType.draft, None, {"prompt": "x"}, _clock())
    with pytest.raises(BrokerError):
        post_result(repo, task.id, {"refused": False})
    # Still pending; nothing written.
    assert repo.get_task(task.id).status == TaskStatus.pending
    assert repo.get_task(task.id).result is None


def test_get_result_returns_result_only_when_done(repo: Repository) -> None:
    task = enqueue(repo, TaskType.draft, None, {"prompt": "x"}, _clock())
    # Pending -> None.
    assert get_result(repo, task.id) is None
    claim(repo, task.id, "worker_1", {"text"})
    # Claimed but not answered -> still None.
    assert get_result(repo, task.id) is None
    post_result(repo, task.id, {"refused": False, "title": "Commit: x"})
    assert get_result(repo, task.id) == {"refused": False, "title": "Commit: x"}


def test_get_result_missing_task_returns_none(repo: Repository) -> None:
    assert get_result(repo, "task_missing") is None

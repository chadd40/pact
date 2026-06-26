from datetime import datetime, timezone

from pact.broker import enqueue, get_result
from pact.clock import FixedClock
from pact.models import TaskStatus, TaskType
from pact.reasoning import TestLLMProvider
from pact.worker import run_once, serve

FIXED = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)


def _clock() -> FixedClock:
    return FixedClock(FIXED)


def test_run_once_resolves_all_handleable_pending_tasks(repo):
    clock = _clock()
    provider = TestLLMProvider()

    t1 = enqueue(
        repo,
        TaskType.draft,
        None,
        {"prompt": "run 5 times this week"},
        clock,
    )
    t2 = enqueue(
        repo,
        TaskType.judge_proof,
        "pact_abc",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        clock,
        required_capability="vision",
    )

    resolved = run_once(repo, provider, "worker-1", clock)

    assert resolved == 2

    done1 = repo.get_task(t1.id)
    done2 = repo.get_task(t2.id)
    assert done1.status == TaskStatus.done
    assert done2.status == TaskStatus.done
    assert done1.claimed_by == "worker-1"
    assert done2.claimed_by == "worker-1"

    # Results are posted and retrievable via the broker.
    r1 = get_result(repo, t1.id)
    r2 = get_result(repo, t2.id)
    assert r1["refused"] is False
    assert r2["status"] == "passed"


def test_run_once_skips_tasks_the_provider_cannot_handle(repo):
    clock = _clock()
    provider = TestLLMProvider()  # capabilities = {"text", "vision"}

    handleable = enqueue(
        repo,
        TaskType.draft,
        None,
        {"prompt": "meditate daily"},
        clock,
    )
    needs_audio = enqueue(
        repo,
        TaskType.judge_proof,
        "pact_xyz",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        clock,
        required_capability="audio",
    )

    resolved = run_once(repo, provider, "worker-1", clock)

    assert resolved == 1
    assert repo.get_task(handleable.id).status == TaskStatus.done
    # Untouched: still pending, never claimed, no result.
    skipped = repo.get_task(needs_audio.id)
    assert skipped.status == TaskStatus.pending
    assert skipped.claimed_by is None
    assert skipped.result is None
    assert get_result(repo, needs_audio.id) is None


def test_run_once_returns_zero_when_no_pending_tasks(repo):
    resolved = run_once(repo, TestLLMProvider(), "worker-1", _clock())
    assert resolved == 0


def test_serve_drains_queue_then_stops(repo):
    clock = _clock()
    provider = TestLLMProvider()

    enqueue(repo, TaskType.draft, None, {"prompt": "walk 5 days"}, clock)
    enqueue(
        repo,
        TaskType.verdict,
        "pact_v",
        {"valid": 5, "target": 5},
        clock,
    )

    total = serve(repo, provider, "worker-1", clock)

    assert total == 2
    # Second pass finds nothing left to do.
    assert run_once(repo, provider, "worker-1", clock) == 0


def test_serve_is_bounded_by_max_rounds(repo):
    clock = _clock()
    provider = TestLLMProvider()

    # One unhandleable task keeps pending_for non-empty forever; max_rounds
    # must still terminate the loop.
    enqueue(
        repo,
        TaskType.judge_proof,
        "pact_b",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        clock,
        required_capability="audio",
    )

    total = serve(repo, provider, "worker-1", clock, max_rounds=3)

    assert total == 0
    assert repo.pending_tasks() != []  # still pending, loop did not hang

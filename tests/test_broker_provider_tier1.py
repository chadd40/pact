from datetime import datetime, timezone

import pytest

from pact import broker
from pact.clock import FixedClock
from pact.models import TaskStatus, TaskType
from pact.reasoning import (
    BrokerReasoningProvider,
    ReasoningUnavailable,
    TestLLMProvider,
    make_reasoning_task,
)
from pact.repository import Repository


@pytest.fixture()
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 6, 25, 12, 0, 0, tzinfo=timezone.utc))


@pytest.fixture()
def repo(tmp_path) -> Repository:
    r = Repository.connect(str(tmp_path / "broker_provider_tier1.db"))
    r.init_schema()
    yield r
    r.close()


def _noop_sleep_recorder():
    """Return (sleep_fn, calls) where calls records every interval slept."""
    calls: list[float] = []

    def sleep(seconds: float) -> None:
        calls.append(seconds)

    return sleep, calls


def test_no_worker_with_fallback_returns_stub_and_enqueues_task(repo, clock):
    """No worker connected + allow_fallback=True:
    - resolve returns the deterministic stub result, AND
    - the task is now visible in the broker as a pending task (it was enqueued).
    """
    sleep, sleep_calls = _noop_sleep_recorder()
    fallback = TestLLMProvider()
    provider = BrokerReasoningProvider(
        repo,
        clock,
        fallback,
        timeout_polls=0,
        sleep=sleep,
        allow_fallback=True,
    )
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_enq",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        clock,
    )

    # Before resolve, the broker has no such task.
    assert repo.get_task(task.id) is None

    result = provider.resolve(task)

    # Fallback (TestLLMProvider) result, deterministic.
    assert result["status"] == "passed"
    assert result["checklist"] == {"token": True, "content": True, "not_dup": True}

    # The task was enqueued so a worker could have claimed it.
    stored = repo.get_task(task.id)
    assert stored is not None
    assert stored.status == TaskStatus.pending
    assert stored.id in {t.id for t in broker.pending_for(repo)}

    # timeout_polls=0 => no polling, so no sleeps at all (fully deterministic).
    assert sleep_calls == []


def test_pre_posted_agent_result_wins_over_fallback(repo, clock):
    """A matching result already posted by an agent is returned verbatim,
    and the fallback is never consulted."""
    sleep, sleep_calls = _noop_sleep_recorder()
    fallback = TestLLMProvider()
    provider = BrokerReasoningProvider(
        repo,
        clock,
        fallback,
        timeout_polls=3,
        sleep=sleep,
        allow_fallback=True,
    )
    # Enqueue the EQUIVALENT task, then mark it done with an agent result that
    # deliberately differs from what the fallback would produce.
    enq = broker.enqueue(
        repo,
        TaskType.judge_proof,
        "pact_agent",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        clock,
    )
    enq.status = TaskStatus.done
    agent_result = {"status": "passed", "reason": "agent reviewed", "checklist": {}}
    enq.result = agent_result
    repo.update_task(enq)

    incoming = make_reasoning_task(
        TaskType.judge_proof,
        "pact_agent",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        clock,
    )
    assert incoming.id == enq.id  # equivalence is id-based

    result = provider.resolve(incoming)

    assert result == agent_result
    assert result["reason"] == "agent reviewed"  # not the fallback's reason
    # Result was available on the first poll, so no sleeps happened.
    assert sleep_calls == []


def test_agent_only_no_result_raises_reasoning_unavailable(repo, clock):
    """allow_fallback=False + no agent result => ReasoningUnavailable,
    and the loop polled+slept exactly timeout_polls times before giving up."""
    sleep, sleep_calls = _noop_sleep_recorder()
    fallback = TestLLMProvider()
    provider = BrokerReasoningProvider(
        repo,
        clock,
        fallback,
        timeout_polls=2,
        sleep=sleep,
        allow_fallback=False,
    )
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_only",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        clock,
    )

    with pytest.raises(ReasoningUnavailable):
        provider.resolve(task)

    # Task was still enqueued so a worker could (later) pick it up.
    stored = repo.get_task(task.id)
    assert stored is not None
    assert stored.status == TaskStatus.pending

    # Polled timeout_polls times with a sleep between each poll attempt.
    assert len(sleep_calls) == 2


def test_capabilities_still_delegate_to_fallback(repo, clock):
    fallback = TestLLMProvider()
    provider = BrokerReasoningProvider(
        repo, clock, fallback, timeout_polls=0, allow_fallback=False
    )
    assert provider.capabilities() == {"text", "vision"}

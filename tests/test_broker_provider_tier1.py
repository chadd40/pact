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


def test_zero_polls_with_fallback_returns_stub_without_enqueuing_orphan(repo, clock):
    """No poll budget + allow_fallback=True: resolve returns the deterministic
    stub result and leaves NO orphan task in the broker -- enqueuing a task no
    worker could claim within a zero-poll window would just leak pending rows."""
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

    assert repo.get_task(task.id) is None

    result = provider.resolve(task)

    # Deterministic stub result.
    assert result["status"] == "passed"
    assert result["checklist"] == {"token": True, "content": True, "not_dup": True}

    # No orphan: nothing was enqueued, the queue is empty.
    assert repo.get_task(task.id) is None
    assert broker.pending_for(repo) == []
    # timeout_polls=0 => no polling, no sleeps.
    assert sleep_calls == []


def test_real_clock_enqueue_id_matches_polled_id_and_agent_result_wins():
    """Regression for the FixedClock-masked id bug: under a RealClock the task
    id must be computed ONCE, so the id resolve() polls is exactly the id a
    worker claims. We simulate a connected worker by resolving the actually-
    enqueued task during the injected sleep; the AGENT result must win. Under the
    old code (id re-derived inside broker.enqueue at a later now()), the enqueued
    id != the polled id and the stub fallback would win, failing this test."""
    from pact.clock import RealClock

    repo = Repository.connect(":memory:")
    repo.init_schema()
    clock = RealClock()
    fallback = TestLLMProvider()
    posted: dict[str, str] = {}

    def worker_sleep(_seconds: float) -> None:
        # A connected worker claims+resolves whatever the provider enqueued.
        pending = broker.pending_for(repo)
        if pending and "id" not in posted:
            t = pending[0]
            broker.claim(repo, t.id, "agent_1", {"text", "vision"})
            broker.post_result(
                repo,
                t.id,
                {"status": "passed", "reason": "agent reviewed", "checklist": {}},
            )
            posted["id"] = t.id

    provider = BrokerReasoningProvider(
        repo, clock, fallback, timeout_polls=3, sleep=worker_sleep, allow_fallback=True
    )
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_rc",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        clock,
    )

    result = provider.resolve(task)

    # The agent's result won -> the enqueued id == the polled id under RealClock.
    assert result["reason"] == "agent reviewed"
    # The enqueued task was claimed+resolved (not left orphaned).
    assert broker.pending_for(repo) == []
    repo.close()


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

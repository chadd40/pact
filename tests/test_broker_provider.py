from datetime import datetime, timezone

import pytest

from pact import broker
from pact.clock import FixedClock
from pact.reasoning import (
    BrokerReasoningProvider,
    TestLLMProvider,
    make_reasoning_task,
)
from pact.models import TaskStatus, TaskType
from pact.repository import Repository


@pytest.fixture()
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 6, 25, 12, 0, 0, tzinfo=timezone.utc))


@pytest.fixture()
def repo(tmp_path) -> Repository:
    r = Repository.connect(str(tmp_path / "broker_provider.db"))
    r.init_schema()
    yield r
    r.close()


def test_capabilities_delegate_to_fallback(repo, clock):
    fallback = TestLLMProvider()
    provider = BrokerReasoningProvider(repo, clock, fallback)
    assert provider.capabilities() == fallback.capabilities()


def test_no_worker_falls_back_to_test_llm_judge(repo, clock):
    fallback = TestLLMProvider()
    provider = BrokerReasoningProvider(repo, clock, fallback, timeout_polls=0)
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_x",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        clock,
    )
    result = provider.resolve(task)
    # Matches TestLLMProvider._judge_proof passed-rule exactly.
    assert result["status"] == "passed"
    assert result["checklist"] == {"token": True, "content": True, "not_dup": True}


def test_no_worker_falls_back_to_test_llm_draft(repo, clock):
    fallback = TestLLMProvider()
    provider = BrokerReasoningProvider(repo, clock, fallback, timeout_polls=0)
    task = make_reasoning_task(
        TaskType.draft, None, {"prompt": "run three times this week"}, clock
    )
    result = provider.resolve(task)
    assert result["refused"] is False
    assert result["target_count"] == 5


def test_pre_posted_result_is_returned_over_fallback(repo, clock):
    fallback = TestLLMProvider()
    provider = BrokerReasoningProvider(repo, clock, fallback, timeout_polls=1)
    # Enqueue the EQUIVALENT task via the broker, then mark it done with an
    # agent-authored result that deliberately differs from the fallback.
    enq = broker.enqueue(
        repo,
        TaskType.judge_proof,
        "pact_y",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        clock,
    )
    enq.status = TaskStatus.done
    agent_result = {"status": "passed", "reason": "agent reviewed", "checklist": {}}
    enq.result = agent_result
    repo.update_task(enq)

    # The incoming task is built the same way -> same deterministic id.
    incoming = make_reasoning_task(
        TaskType.judge_proof,
        "pact_y",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        clock,
    )
    assert incoming.id == enq.id  # sanity: equivalence is id-based
    result = provider.resolve(incoming)
    assert result == agent_result
    assert result["reason"] == "agent reviewed"  # not the fallback's reason


def test_pre_posted_not_done_falls_back(repo, clock):
    fallback = TestLLMProvider()
    provider = BrokerReasoningProvider(repo, clock, fallback, timeout_polls=1)
    # Equivalent task exists but is still pending (no worker finished it).
    broker.enqueue(
        repo,
        TaskType.judge_proof,
        "pact_z",
        {"token_ok": False, "is_duplicate": False, "content_ok": True},
        clock,
    )
    incoming = make_reasoning_task(
        TaskType.judge_proof,
        "pact_z",
        {"token_ok": False, "is_duplicate": False, "content_ok": True},
        clock,
    )
    result = provider.resolve(incoming)
    # Falls back to TestLLMProvider: token_ok False -> failed.
    assert result["status"] == "failed"
    assert result["reason"] == "Required nonce token not verified; rejecting proof."

from datetime import datetime, timezone

from pact.clock import FixedClock
from pact.models import Modality, TaskStatus, TaskType
from pact.reasoning import TestLLMProvider, make_reasoning_task


FIXED = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)


def _clock() -> FixedClock:
    return FixedClock(FIXED)


def test_make_reasoning_task_builds_pending_task():
    clock = _clock()
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_abc123",
        {"token_ok": True},
        clock,
        required_capability="vision",
    )
    assert task.type == TaskType.judge_proof
    assert task.pact_id == "pact_abc123"
    assert task.input == {"token_ok": True}
    assert task.required_capability == "vision"
    assert task.status == TaskStatus.pending
    assert task.result is None
    assert task.claimed_by is None
    assert task.created_at == FIXED
    assert isinstance(task.id, str) and task.id


def test_make_reasoning_task_defaults_capability_none_and_allows_no_pact():
    task = make_reasoning_task(TaskType.draft, None, {"prompt": "x"}, _clock())
    assert task.pact_id is None
    assert task.required_capability is None


def test_provider_capabilities_are_text_and_vision():
    assert TestLLMProvider().capabilities() == {"text", "vision"}


def test_resolve_draft_returns_full_rubric_and_stake():
    provider = TestLLMProvider()
    task = make_reasoning_task(
        TaskType.draft, None, {"prompt": "work out 5x this week"}, _clock()
    )
    result = provider.resolve(task)
    assert result["refused"] is False
    assert isinstance(result["reason"], str)
    for key in (
        "title",
        "goal",
        "timezone",
        "deadline_iso",
        "target_count",
        "recommended_stake_cents",
        "rubric",
    ):
        assert key in result
    assert isinstance(result["recommended_stake_cents"], int)
    assert result["recommended_stake_cents"] > 0
    rubric = result["rubric"]
    for key in (
        "modality",
        "require_token",
        "must_show",
        "reject_if",
        "min_distinct_days",
        "count_target",
        "rest_if_injured_counts",
        "rigor_floor",
    ):
        assert key in rubric
    assert rubric["modality"] in {m.value for m in Modality}
    assert isinstance(rubric["must_show"], list) and rubric["must_show"]
    assert isinstance(rubric["rigor_floor"], dict)


def test_resolve_judge_proof_passes_only_when_all_good():
    provider = TestLLMProvider()
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_abc123",
        {"token_ok": True, "is_duplicate": False, "content_ok": True, "rubric": {}},
        _clock(),
    )
    result = provider.resolve(task)
    assert result["status"] == "passed"
    assert result["checklist"] == {"token": True, "content": True, "not_dup": True}
    assert isinstance(result["reason"], str)


def test_resolve_judge_proof_not_token_is_failed():
    provider = TestLLMProvider()
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_abc123",
        {"token_ok": False, "is_duplicate": False, "content_ok": True, "rubric": {}},
        _clock(),
    )
    result = provider.resolve(task)
    assert result["status"] == "failed"
    assert result["checklist"]["token"] is False


def test_resolve_judge_proof_duplicate_is_failed():
    provider = TestLLMProvider()
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_abc123",
        {"token_ok": True, "is_duplicate": True, "content_ok": True, "rubric": {}},
        _clock(),
    )
    result = provider.resolve(task)
    assert result["status"] == "failed"
    assert result["checklist"]["not_dup"] is False


def test_resolve_judge_proof_bad_content_is_ambiguous():
    provider = TestLLMProvider()
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_abc123",
        {"token_ok": True, "is_duplicate": False, "content_ok": False, "rubric": {}},
        _clock(),
    )
    result = provider.resolve(task)
    assert result["status"] == "ambiguous"
    assert result["checklist"] == {"token": True, "content": False, "not_dup": True}


def test_resolve_judge_proof_image_without_vision_judge_is_ambiguous_not_passed():
    # An image proof reaches the DETERMINISTIC fallback with an artifact_path but
    # no explicit content_ok (only a vision-capable agent can set that). The
    # fallback has no vision, so it must NOT rubber-stamp the image as passed --
    # it holds it as ambiguous for review.
    provider = TestLLMProvider()
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_abc123",
        {
            "token_ok": True,
            "is_duplicate": False,
            "artifact_path": "/tmp/proof.jpg",
            "phash": "deadbeef",
            "rubric": {},
            "modality": "photo",
        },
        _clock(),
    )
    result = provider.resolve(task)
    assert result["status"] == "ambiguous"
    assert result["checklist"] == {"token": True, "content": False, "not_dup": True}
    assert "vision" in result["reason"].lower()


def test_resolve_judge_proof_image_with_explicit_content_ok_is_honored():
    # When a (vision-capable) caller DOES assert content_ok alongside an
    # artifact_path, the deterministic judge honors that explicit signal.
    provider = TestLLMProvider()
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_abc123",
        {
            "token_ok": True,
            "is_duplicate": False,
            "content_ok": True,
            "artifact_path": "/tmp/proof.jpg",
            "rubric": {},
            "modality": "photo",
        },
        _clock(),
    )
    result = provider.resolve(task)
    assert result["status"] == "passed"
    assert result["checklist"] == {"token": True, "content": True, "not_dup": True}


def test_resolve_coach_message_contains_pace_math():
    provider = TestLLMProvider()
    task = make_reasoning_task(
        TaskType.coach,
        "pact_abc123",
        {"valid": 2, "target": 5, "days_left": 2, "charity": "World Central Kitchen"},
        _clock(),
    )
    result = provider.resolve(task)
    message = result["message"]
    assert "2" in message and "5" in message
    assert "3" in message  # remaining = target - valid
    assert "World Central Kitchen" in message


def test_resolve_verdict_returns_summary():
    provider = TestLLMProvider()
    task = make_reasoning_task(
        TaskType.verdict, "pact_abc123", {"valid": 4, "target": 5}, _clock()
    )
    result = provider.resolve(task)
    assert "4" in result["summary"] and "5" in result["summary"]

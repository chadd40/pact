import hashlib
from typing import Protocol

from .clock import Clock
from .models import ReasoningTask, TaskStatus, TaskType


class ReasoningProvider(Protocol):
    def capabilities(self) -> set[str]:
        ...

    def resolve(self, task: ReasoningTask) -> dict:
        ...


def make_reasoning_task(
    type: TaskType,
    pact_id: str | None,
    input: dict,
    clock: Clock,
    required_capability: str | None = None,
) -> ReasoningTask:
    now = clock.now()
    seed = f"{type.value}:{pact_id}:{now.isoformat()}:{sorted(input.items())!r}"
    task_id = "task_" + hashlib.sha1(seed.encode()).hexdigest()[:8]
    return ReasoningTask(
        id=task_id,
        pact_id=pact_id,
        type=type,
        required_capability=required_capability,
        input=input,
        status=TaskStatus.pending,
        result=None,
        claimed_by=None,
        created_at=now,
    )


class TestLLMProvider:
    """Deterministic reasoning stub for demos/tests and the hybrid fallback."""

    def capabilities(self) -> set[str]:
        return {"text", "vision"}

    def resolve(self, task: ReasoningTask) -> dict:
        if task.type == TaskType.draft:
            return self._draft(task.input)
        if task.type == TaskType.judge_proof:
            return self._judge_proof(task.input)
        if task.type == TaskType.coach:
            return self._coach(task.input)
        if task.type == TaskType.verdict:
            return self._verdict(task.input)
        raise ValueError(f"unsupported task type: {task.type}")

    _REFUSAL_PHRASES = [
        "every single day no rest",
        "no rest ever",
        "no days off ever",
    ]

    def _draft(self, input: dict) -> dict:
        prompt = str(input.get("prompt", "")).strip()
        if not prompt:
            return {
                "refused": True,
                "reason": "Empty prompt; nothing to commit to.",
                "title": "",
                "goal": "",
                "timezone": "America/Los_Angeles",
                "deadline_iso": "",
                "target_count": 0,
                "recommended_stake_cents": 0,
                "rubric": {},
            }
        lower = prompt.lower()
        for phrase in self._REFUSAL_PHRASES:
            if phrase in lower:
                return {
                    "refused": True,
                    "reason": "Prompt describes an unrealistic or harmful commitment; refusing.",
                    "title": "",
                    "goal": "",
                    "timezone": "America/Los_Angeles",
                    "deadline_iso": "",
                    "target_count": 0,
                    "recommended_stake_cents": 0,
                    "rubric": {},
                }
        rubric = {
            "modality": "photo",
            "require_token": True,
            "must_show": ["clear evidence the committed action was performed"],
            "reject_if": ["stock/watermark", "pure UI screenshot", "missing token"],
            "min_distinct_days": 5,
            "count_target": 5,
            "rest_if_injured_counts": True,
            "rigor_floor": {
                "require_token": True,
                "min_distinct_days": 4,
                "non_negotiable": [
                    "require_token",
                    "server_time_is_truth",
                    "no_duplicates",
                ],
            },
        }
        return {
            "refused": False,
            "reason": "Goal is concrete and checkable.",
            "title": "Commit: " + prompt[:48],
            "goal": "Complete the committed action 5 times on 5 distinct days.",
            "timezone": "America/Los_Angeles",
            "deadline_iso": "2026-06-28T23:59:59-07:00",
            "target_count": 5,
            "recommended_stake_cents": 2000,
            "rubric": rubric,
        }

    def _judge_proof(self, input: dict) -> dict:
        token_ok = bool(input.get("token_ok"))
        is_duplicate = bool(input.get("is_duplicate"))
        content_ok = bool(input.get("content_ok"))
        checklist = {
            "token": token_ok,
            "content": content_ok,
            "not_dup": not is_duplicate,
        }
        if not token_ok:
            status = "failed"
            reason = "Required nonce token not verified; rejecting proof."
        elif is_duplicate:
            status = "failed"
            reason = "Perceptual hash matches a prior proof; duplicate rejected."
        elif not content_ok:
            status = "ambiguous"
            reason = "Token valid but content does not clearly satisfy the rubric."
        else:
            status = "passed"
            reason = "Token verified, content satisfies rubric, no duplicate."
        return {"status": status, "reason": reason, "checklist": checklist}

    def _coach(self, input: dict) -> dict:
        valid = int(input.get("valid", 0))
        target = int(input.get("target", 0))
        days_left = int(input.get("days_left", 0))
        charity = str(input.get("charity", "your chosen charity"))
        remaining = max(target - valid, 0)
        message = (
            f"{valid} of {target} done, {days_left} days left "
            f"— you need {remaining} more to keep your stake out of "
            f"{charity}."
        )
        return {"message": message}

    def _verdict(self, input: dict) -> dict:
        valid = int(input.get("valid", 0))
        target = int(input.get("target", 0))
        outcome = "Pact succeeded." if valid >= target else "Pact failed."
        summary = f"{valid} of {target} valid distinct-day proofs by deadline. {outcome}"
        return {"summary": summary}

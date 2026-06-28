import hashlib
import time
from typing import Protocol, runtime_checkable

from .clock import Clock
from .models import ReasoningTask, TaskStatus, TaskType


@runtime_checkable
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

    # §9 intake safety gate: (category_reason, trigger_substrings).
    # First matching category wins; reason is short and category-specific.
    _REFUSAL_CATEGORIES = [
        (
            "Refusing: self-harm or self-punishment goals are not allowed. "
            "If you're struggling, you're not alone — in the US you can call "
            "or text 988 (Suicide & Crisis Lifeline).",
            [
                "hurt myself",
                "harm myself",
                "punish myself",
                "self-harm",
                "self harm",
                "self-punish",
            ],
        ),
        (
            "Refusing: weight-loss-rate goals (losing a set amount of weight in "
            "a short window) are unsafe to stake.",
            [
                "lose 5 pounds",
                "lose 8 pounds",
                "lose 10 pounds",
                "lose 15 pounds",
                "lose 20 pounds",
                "pounds in",
                "lbs this week",
                "lbs in",
                "drop 8 lbs",
                "drop 10 lbs",
            ],
        ),
        (
            "Refusing: calorie-restriction, fasting, or purging goals are unsafe "
            "to stake. If eating feels out of control, please reach out for "
            "support — in the US you can call or text 988.",
            [
                "under 800 calories",
                "calorie deficit",
                "starve",
                "fast for",
                "fasting",
                "purge",
                "vomit",
                "skip meals",
            ],
        ),
        (
            "Refusing: 'every single day with no rest' exercise goals are unsafe. "
            "A safe pact caps frequency and bakes in a rest day.",
            [
                "every single day",
                "every day with no rest",
                "no rest",
                "no days off",
                "7 days straight",
                "seven days straight",
                "no rest day",
            ],
        ),
        (
            "Refusing: goals that train through injury or pain are unsafe. "
            "Rest while injured still counts as keeping the pact.",
            [
                "injury",
                "injured",
                "through the pain",
                "ignore the pain",
                "push through pain",
            ],
        ),
        (
            "Refusing: a pact can only stake your own behavior — you can't put "
            "someone else on the hook or stake against another person.",
            [
                "make my brother",
                "make my sister",
                "make my friend",
                "make him pay",
                "make her pay",
                "make them pay",
                "if i don't finish",
                "force my",
            ],
        ),
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
        for reason, phrases in self._REFUSAL_CATEGORIES:
            if any(phrase in lower for phrase in phrases):
                return {
                    "refused": True,
                    "reason": reason,
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


class ReasoningUnavailable(Exception):
    """Raised when agent reasoning is required (no fallback allowed) but no
    worker posted a result before the poll budget was exhausted."""


class BrokerReasoningProvider:
    """Hybrid provider: enqueue the task so a connected worker can claim it,
    poll the broker for an agent-posted result up to ``timeout_polls`` times,
    and either return that result, fall back to the deterministic stub
    (``allow_fallback=True``), or raise :class:`ReasoningUnavailable`
    (``allow_fallback=False``).

    Equivalence is by deterministic task id: two tasks with the same
    (type, pact_id, sorted(input), required_capability, clock.now()) map to the
    same id via ``make_reasoning_task``. The task is enqueued only when no task
    with that id already exists, so an already-posted ``done`` result is never
    overwritten back to ``pending``.

    ``sleep`` is injected (defaults to ``time.sleep``) so tests pass a no-op and
    stay deterministic; ``timeout_polls=0`` means "no agent connected -> enqueue
    then immediately fall back / raise" with no sleeping.
    """

    def __init__(
        self,
        repo,
        clock,
        fallback: "ReasoningProvider",
        timeout_polls: int = 0,
        sleep=time.sleep,
        allow_fallback: bool = True,
        poll_interval_seconds: float = 0.5,
        worker_present=None,
    ) -> None:
        self.repo = repo
        self.clock = clock
        self.fallback = fallback
        self.timeout_polls = timeout_polls
        self.sleep = sleep
        self.allow_fallback = allow_fallback
        self.poll_interval_seconds = poll_interval_seconds
        # Optional liveness probe: a zero-arg callable returning True iff a
        # reasoning worker is currently serving. When provided and it reports no
        # worker, fallback-allowed resolves skip the enqueue/poll entirely (no
        # multi-second hang waiting for an agent that isn't there). Default None
        # preserves the original poll-budget-only behavior.
        self._worker_present = worker_present

    def capabilities(self) -> set[str]:
        return self.fallback.capabilities()

    def resolve(self, task: ReasoningTask) -> dict:
        from . import broker  # lazy import to avoid a circular import

        # Fallback-allowed and there's no point waiting for an agent: resolve via
        # the stub directly and do NOT leave an unclaimable orphan task in the
        # broker. That's true when either the poll budget is zero (no window for a
        # worker to post) OR a liveness probe says no worker is currently serving
        # (so polling would just burn the full budget then fall back anyway).
        if self.allow_fallback:
            no_budget = self.timeout_polls == 0
            no_worker = self._worker_present is not None and not self._worker_present()
            if no_budget or no_worker:
                return self.fallback.resolve(task)

        # Build the equivalent task ONCE and enqueue THAT EXACT task, so the id
        # we poll is the id a worker claims. (Calling broker.enqueue would
        # re-derive the id from a later clock.now() under a RealClock, yielding a
        # DIFFERENT id than the one we poll -- the agent's posted result would
        # then never be found, silently falling back to the stub. That bug is
        # invisible under a FixedClock because both instants are identical.)
        equivalent = make_reasoning_task(
            task.type,
            task.pact_id,
            task.input,
            self.clock,
            task.required_capability,
        )
        # Enqueue only if not already present (don't clobber an in-flight/done task).
        if self.repo.get_task(equivalent.id) is None:
            self.repo.save_task(equivalent)

        # Poll for an agent-posted result on THAT id. A result already present is
        # found on the first read; otherwise sleep between attempts.
        result = broker.get_result(self.repo, equivalent.id)
        for _ in range(self.timeout_polls):
            if result is not None:
                return result
            self.sleep(self.poll_interval_seconds)
            result = broker.get_result(self.repo, equivalent.id)
        if result is not None:
            return result

        if self.allow_fallback:
            return self.fallback.resolve(task)
        raise ReasoningUnavailable(
            f"no agent result for task {equivalent.id} after "
            f"{self.timeout_polls} polls and fallback is disabled"
        )

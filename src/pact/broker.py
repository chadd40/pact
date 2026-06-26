from __future__ import annotations

from .clock import Clock
from .models import ReasoningTask, TaskStatus, TaskType
from .reasoning import make_reasoning_task
from .repository import Repository


class BrokerError(Exception):
    """Raised when a broker state transition is not allowed.

    (Missing tasks raise KeyError; this covers double-claim, posting a result
    before claiming, and capability mismatches.)
    """


def enqueue(
    repo: Repository,
    type: TaskType,
    pact_id: str | None,
    input: dict,
    clock: Clock,
    required_capability: str | None = None,
) -> ReasoningTask:
    """Build a pending reasoning task and persist it; return it."""
    task = make_reasoning_task(
        type,
        pact_id,
        input,
        clock,
        required_capability=required_capability,
    )
    repo.save_task(task)
    return task


def pending_for(
    repo: Repository, capability: str | None = None
) -> list[ReasoningTask]:
    """Pending tasks; if capability is given, only those requiring exactly it.

    capability=None returns every pending task (any capability).
    """
    return repo.pending_tasks(capability=capability)


def claim(
    repo: Repository,
    task_id: str,
    agent_name: str,
    capabilities: set[str],
) -> ReasoningTask:
    """Claim a pending task for a worker.

    Raises KeyError if the task does not exist; BrokerError if it is not
    pending (already claimed/done) or the worker lacks the required capability.
    """
    task = repo.get_task(task_id)
    if task is None:
        raise KeyError(f"unknown task: {task_id}")
    if task.status != TaskStatus.pending:
        raise BrokerError(
            f"task {task_id} is {task.status.value}, not pending; cannot claim"
        )
    if (
        task.required_capability is not None
        and task.required_capability not in capabilities
    ):
        raise BrokerError(
            f"worker {agent_name} lacks capability "
            f"{task.required_capability!r} for task {task_id}"
        )
    claimed = task.model_copy(
        update={"status": TaskStatus.claimed, "claimed_by": agent_name}
    )
    repo.update_task(claimed)
    return claimed


def post_result(repo: Repository, task_id: str, result: dict) -> ReasoningTask:
    """Attach a result to a claimed task and mark it done.

    Raises KeyError if the task does not exist; BrokerError if it has not been
    claimed (results may only be posted for claimed tasks).
    """
    task = repo.get_task(task_id)
    if task is None:
        raise KeyError(f"unknown task: {task_id}")
    if task.status != TaskStatus.claimed:
        raise BrokerError(
            f"task {task_id} is {task.status.value}, not claimed; "
            "cannot post result"
        )
    done = task.model_copy(update={"status": TaskStatus.done, "result": result})
    repo.update_task(done)
    return done


def get_result(repo: Repository, task_id: str) -> dict | None:
    """Return the task's result only when it is done; otherwise None."""
    task = repo.get_task(task_id)
    if task is None or task.status != TaskStatus.done:
        return None
    return task.result

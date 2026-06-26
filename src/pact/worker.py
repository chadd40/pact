"""The `/pact serve` worker: drain the reasoning-task broker queue.

A worker repeatedly claims pending tasks it is capable of handling, resolves
them with its ReasoningProvider, and posts the result back through the broker.

SAFETY: this only resolves reasoning tasks (draft/judge/coach/verdict). It never
moves money or sends email — those live behind the scheduler / payment / notify
modules. The `pact serve` CLI hook simply loops `serve` against a live API repo.
"""

from __future__ import annotations

from .broker import claim, pending_for, post_result
from .clock import Clock
from .reasoning import ReasoningProvider


def _can_handle(task, capabilities: set[str]) -> bool:
    """A task is handleable when it requires no capability, or one we have."""
    if task.required_capability is None:
        return True
    return task.required_capability in capabilities


def run_once(
    repo,
    provider: ReasoningProvider,
    agent_name: str,
    clock: Clock,
) -> int:
    """Claim+resolve+post every pending task this provider can handle.

    Returns the number of tasks resolved in this pass. Tasks whose
    required_capability the provider lacks are left untouched (pending).
    """
    capabilities = provider.capabilities()
    resolved = 0
    for task in pending_for(repo):
        if not _can_handle(task, capabilities):
            continue
        claimed = claim(repo, task.id, agent_name, capabilities)
        result = provider.resolve(claimed)
        post_result(repo, claimed.id, result)
        resolved += 1
    return resolved


def serve(
    repo,
    provider: ReasoningProvider,
    agent_name: str,
    clock: Clock,
    max_rounds: int | None = None,
) -> int:
    """Loop `run_once` until a pass resolves nothing (queue drained), or until
    `max_rounds` passes have run. Returns the total number of tasks resolved.

    `max_rounds` bounds the loop for tests and guarantees termination even when
    unhandleable tasks keep `pending_for` non-empty.
    """
    total = 0
    rounds = 0
    while True:
        if max_rounds is not None and rounds >= max_rounds:
            break
        count = run_once(repo, provider, agent_name, clock)
        rounds += 1
        total += count
        if count == 0:
            break
    return total

"""HTTP-backed reasoning worker: drain a LIVE server's broker queue over HTTP.

This is the runnable worker a Hermes agent (or the deterministic
``TestLLMProvider`` stub) uses against a running Pact API. It only touches the
``/api/reasoning-tasks`` routes — it never moves money or delivers coaching
nudges (those live behind the scheduler/outbox). ``relay_outbox`` is the
companion that drains ``/api/outbox`` and marks each message delivered.

Determinism: every method is a single synchronous HTTP round-trip. Tests inject
an ``httpx.Client`` wired to an in-process ASGI app via ``httpx.ASGITransport``,
so there is no real network, subprocess, or sleep.
"""

from __future__ import annotations

from datetime import datetime

import httpx

from .models import ReasoningTask, TaskStatus, TaskType
from .reasoning import ReasoningProvider


class HttpWorkerClient:
    """Thin sync HTTP client over the broker's reasoning-task routes."""

    def __init__(self, base_url: str, http: httpx.Client | None = None) -> None:
        self.base_url = base_url
        # Tests inject an httpx.Client bound to the ASGI app; otherwise talk to
        # a real server at base_url.
        self.http = http if http is not None else httpx.Client(base_url=base_url)

    def pending(self, capability: str | None = None) -> list[dict]:
        params = {} if capability is None else {"capability": capability}
        r = self.http.get("/api/reasoning-tasks", params=params)
        r.raise_for_status()
        return r.json()

    def claim(self, task_id: str, agent_name: str, capabilities) -> dict:
        r = self.http.post(
            f"/api/reasoning-tasks/{task_id}/claim",
            json={"agent_name": agent_name, "capabilities": list(capabilities)},
        )
        r.raise_for_status()
        return r.json()

    def post_result(self, task_id: str, result: dict) -> dict:
        r = self.http.post(
            f"/api/reasoning-tasks/{task_id}/result",
            json={"result": result},
        )
        r.raise_for_status()
        return r.json()


def _can_handle(required_capability: str | None, capabilities: set[str]) -> bool:
    """Mirror worker._can_handle: no requirement, or a capability we hold."""
    if required_capability is None:
        return True
    return required_capability in capabilities


def _task_from_dict(data: dict) -> ReasoningTask:
    """Rebuild a ReasoningTask from a claim/list response payload."""
    return ReasoningTask(
        id=data["id"],
        pact_id=data.get("pact_id"),
        type=TaskType(data["type"]),
        required_capability=data.get("required_capability"),
        input=data.get("input", {}),
        status=TaskStatus(data["status"]),
        result=data.get("result"),
        claimed_by=data.get("claimed_by"),
        created_at=datetime.fromisoformat(data["created_at"]),
    )


def serve_http(
    client: HttpWorkerClient,
    provider: ReasoningProvider,
    agent_name: str,
    max_rounds: int = 1,
) -> int:
    """Drain pending tasks this provider can handle, over HTTP.

    Loops up to ``max_rounds`` times: list pending tasks; for each task whose
    required capability the provider holds, claim it, resolve it, and post the
    result back. Capability-mismatch tasks are SKIPPED without claiming (left
    pending for a more-capable worker). Returns the number of tasks resolved.

    A round that resolves nothing stops the loop early (queue drained for us).
    """
    capabilities = provider.capabilities()
    resolved = 0
    for _ in range(max_rounds):
        count_this_round = 0
        for entry in client.pending():
            if not _can_handle(entry.get("required_capability"), capabilities):
                continue
            claimed = client.claim(entry["id"], agent_name, capabilities)
            task = _task_from_dict(claimed)
            result = provider.resolve(task)
            client.post_result(task.id, result)
            resolved += 1
            count_this_round += 1
        if count_this_round == 0:
            break
    return resolved


def relay_outbox(client_or_http, base_url, owner, deliver=None) -> int:
    """Relay the owner's undelivered coaching nudges out of the live server.

    For each message in GET /api/outbox?owner=<owner>: call ``deliver(msg)``
    (the Hermes agent ships it over its own channel; the default just returns
    the message, i.e. a no-op log), then POST /api/coach/{id}/delivered so it
    leaves the outbox. Returns the number of messages relayed.

    ``client_or_http`` may be an :class:`HttpWorkerClient` (its ``.http`` is
    used) or a raw ``httpx.Client``. ``base_url`` is accepted for symmetry with
    the CLI and prepended only when the http client has no ``base_url`` of its
    own; in the in-process ASGI tests the client is already bound to the app's
    base_url, so the relative paths below resolve correctly.
    """
    http = getattr(client_or_http, "http", client_or_http)
    if deliver is None:
        def deliver(msg):  # default: no-op "log" that just echoes the message
            return msg

    resp = http.get("/api/outbox", params={"owner": owner})
    resp.raise_for_status()
    messages = resp.json()

    relayed = 0
    for msg in messages:
        deliver(msg)
        marked = http.post(f"/api/coach/{msg['id']}/delivered")
        marked.raise_for_status()
        relayed += 1
    return relayed

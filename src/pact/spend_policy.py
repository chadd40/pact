"""Deterministic spend policy — the core of the agent spend gate.

Pact lets a user authorise an agent to spend money ("agent may spend up to $X,
to approved charities, only on a verified miss"). Before any donation fires, the
proposed spend is checked against that policy. This module is pure: no I/O, no
model calls — just the decision. ``pact.guardrails`` builds the per-owner policy
and exposes the gate; the settlement chokepoints (``pact.lifecycle`` / the live
donation endpoints) call it before ``payment.create_donation``.

Keeping the decision deterministic means the money path's correctness never
depends on an LLM or a network round-trip — the gate is enforcement, not a
suggestion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SpendRequest:
    """A proposed spend the agent wants to make on the owner's behalf."""

    owner: str
    amount_cents: int
    charity_id: str
    verified_failure: bool


@dataclass(frozen=True)
class SpendPolicy:
    """The owner's spending authorisation for their agent.

    - ``max_cents``: the agent may spend at most this per donation. ``None`` =
      no extra ceiling beyond Pact's per-stake cap.
    - ``charity_allowlist``: the agent may only pay these charity ids. ``None`` =
      any charity (in practice the API passes the known-charity catalogue, so an
      unknown merchant is rejected).
    - ``require_verified_failure``: the agent may only spend on a genuinely
      verified commitment miss. Defaults on — this is a non-negotiable rail.
    """

    max_cents: int | None = None
    charity_allowlist: frozenset[str] | None = None
    require_verified_failure: bool = True


@dataclass(frozen=True)
class GateDecision:
    """The outcome of a spend check, with a human-readable reason for the UI and
    the evidence packet. ``rail`` records which layer produced the decision
    (``spend_policy`` for the deterministic gate)."""

    allowed: bool
    reason: str
    rail: str = "spend_policy"


@runtime_checkable
class SpendGate(Protocol):
    """Anything that can rule on a proposed spend. The ``SpendGuard`` and test
    fakes all satisfy this."""

    def check(self, request: SpendRequest) -> GateDecision:
        ...


def _dollars(cents: int) -> str:
    return f"${cents / 100:.2f}"


def evaluate(request: SpendRequest, policy: SpendPolicy) -> GateDecision:
    """Decide whether a proposed spend is permitted by the owner's policy.

    Checks run cheapest-and-most-fundamental first: verified-failure, then the
    charity allowlist, then the dollar ceiling. The first failing check wins.
    """
    if policy.require_verified_failure and not request.verified_failure:
        return GateDecision(
            allowed=False,
            reason="Spend blocked: the commitment failure is not verified, so no money may move.",
        )

    if (
        policy.charity_allowlist is not None
        and request.charity_id not in policy.charity_allowlist
    ):
        return GateDecision(
            allowed=False,
            reason=(
                f"Spend blocked: '{request.charity_id}' is not on the approved "
                "charity allowlist."
            ),
        )

    if policy.max_cents is not None and request.amount_cents > policy.max_cents:
        return GateDecision(
            allowed=False,
            reason=(
                f"Spend blocked: {_dollars(request.amount_cents)} exceeds the "
                f"agent's {_dollars(policy.max_cents)} spend limit."
            ),
        )

    return GateDecision(
        allowed=True,
        reason=(
            f"Spend approved: {_dollars(request.amount_cents)} to "
            f"'{request.charity_id}' is within policy."
        ),
    )

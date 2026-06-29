"""Deterministic spend gate for agent spending.

The actual protection is the deterministic policy in ``pact.spend_policy`` (amount
ceiling + approved-charity allowlist + verified-failure). This module is a thin
adapter that builds the per-owner policy and exposes a ``SpendGate`` the
settlement chokepoints call before any money moves.

(Earlier this wrapped NVIDIA NeMo Guardrails; that heavy dependency was dropped in
favour of the equivalent deterministic check — same decision, no framework. The
NVIDIA integration lives in ``pact.reasoning`` (Nemotron via NIM) instead.)
"""

from __future__ import annotations

from pact.charities import all_charity_ids
from pact.models import Profile
from pact.spend_policy import GateDecision, SpendPolicy, SpendRequest, evaluate


class SpendGuard:
    """A :class:`~pact.spend_policy.SpendGate` over a fixed policy."""

    def __init__(self, policy: SpendPolicy):
        self._policy = policy

    @property
    def active_rail(self) -> str:
        return "spend_policy"

    def check(self, request: SpendRequest) -> GateDecision:
        return evaluate(request, self._policy)


def policy_for_profile(profile: Profile | None) -> SpendPolicy:
    """Build the spend policy for an owner: their configured agent spend limit,
    restricted to Pact's known-charity catalogue (so an unknown merchant is
    rejected), and only on a verified miss."""
    max_cents = profile.spend_limit_cents if profile else None
    return SpendPolicy(
        max_cents=max_cents,
        charity_allowlist=frozenset(all_charity_ids()),
        require_verified_failure=True,
    )


def build_spend_guard(profile: Profile | None) -> SpendGuard:
    """A deterministic spend guard for an owner's policy."""
    return SpendGuard(policy_for_profile(profile))

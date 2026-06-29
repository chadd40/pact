"""NeMo Guardrails enforcement layer for agent spending ("NemoGuard").

Pact's spend decision is deterministic (see ``pact.spend_policy.evaluate``).
This module runs that decision *through the NVIDIA NeMo Guardrails runtime* by
registering it as a custom action and invoking it via the runtime's action
dispatcher. That makes the guardrail genuine enforcement — every proposed spend
executes through NeMo Guardrails before any money can move — while keeping the
decision LLM-free and key-free: the rails config declares no models, so no
NVIDIA API key or network round-trip is required for the gate.

If ``nemoguardrails`` is unavailable (e.g. a slimmed packaged build), the guard
falls back to calling ``evaluate`` directly so the money path stays protected;
the only difference is the decision's ``rail`` label (``spend_policy`` instead of
``nemoguard``).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging

from pact.charities import all_charity_ids
from pact.models import Profile
from pact.spend_policy import GateDecision, SpendPolicy, SpendRequest, evaluate

logger = logging.getLogger(__name__)

try:  # nemoguardrails is an optional-but-expected dependency.
    from nemoguardrails import LLMRails, RailsConfig
    from nemoguardrails.actions import action

    _NEMOGUARD_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only in slimmed builds
    _NEMOGUARD_AVAILABLE = False

# A models-free rails config: the spend action is deterministic, so the runtime
# never needs an LLM to reach a verdict. This is what lets the gate run with no
# NVIDIA key.
_RAILS_YAML = "models: []\n"

_ACTION_NAME = "check_spend_policy"


def _run_coro(coro):
    """Run a coroutine from sync code, whether or not a loop is already running.

    FastAPI's sync path operations run in a worker thread with no running loop,
    so ``asyncio.run`` works directly. The thread-pool branch keeps the guard
    usable if it is ever called from inside an event loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro)).result()


class SpendGuard:
    """A :class:`~pact.spend_policy.SpendGate` backed by NeMo Guardrails."""

    def __init__(self, policy: SpendPolicy):
        self._policy = policy
        self._rails = None
        if _NEMOGUARD_AVAILABLE:
            try:
                self._rails = self._build_rails(policy)
            except Exception:  # pragma: no cover - defensive
                logger.exception(
                    "NeMo Guardrails init failed; falling back to deterministic policy"
                )
                self._rails = None

    @property
    def active_rail(self) -> str:
        """Which enforcement path this guard will use: 'nemoguard' or 'spend_policy'."""
        return "nemoguard" if self._rails is not None else "spend_policy"

    @staticmethod
    def _build_rails(policy: SpendPolicy):
        config = RailsConfig.from_content(yaml_content=_RAILS_YAML)
        rails = LLMRails(config)

        @action(name=_ACTION_NAME)
        async def check_spend_policy(
            amount_cents: int = 0,
            charity_id: str = "",
            verified_failure: bool = False,
        ) -> dict:
            decision = evaluate(
                SpendRequest(
                    owner="",
                    amount_cents=amount_cents,
                    charity_id=charity_id,
                    verified_failure=verified_failure,
                ),
                policy,
            )
            return {"allowed": decision.allowed, "reason": decision.reason}

        rails.register_action(check_spend_policy, name=_ACTION_NAME)
        return rails

    def check(self, request: SpendRequest) -> GateDecision:
        if self._rails is None:
            decision = evaluate(request, self._policy)
            return GateDecision(decision.allowed, decision.reason, rail="spend_policy")
        try:
            result, status = _run_coro(
                self._rails.runtime.action_dispatcher.execute_action(
                    _ACTION_NAME,
                    {
                        "amount_cents": request.amount_cents,
                        "charity_id": request.charity_id,
                        "verified_failure": request.verified_failure,
                    },
                )
            )
            if status != "success" or not isinstance(result, dict):
                raise RuntimeError(f"guardrail action returned status={status!r}")
            return GateDecision(
                allowed=bool(result["allowed"]),
                reason=str(result["reason"]),
                rail="nemoguard",
            )
        except Exception:  # pragma: no cover - defensive fallback
            logger.exception(
                "NeMo Guardrails check failed; falling back to deterministic policy"
            )
            decision = evaluate(request, self._policy)
            return GateDecision(decision.allowed, decision.reason, rail="spend_policy")


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
    """Convenience: a NeMo Guardrails spend guard for an owner's policy."""
    return SpendGuard(policy_for_profile(profile))

from __future__ import annotations

from pact.clock import Clock
from pact.config import Settings
from pact.payment import PaymentProvider, get_payment_provider
from pact.reasoning import (
    BrokerReasoningProvider,
    ReasoningProvider,
    TestLLMProvider,
)
from pact.repository import Repository


def build_reasoning_provider(
    settings: Settings,
    repo: Repository,
    clock: Clock,
    fallback: ReasoningProvider | None = None,
) -> ReasoningProvider:
    """Select the reasoning provider from Settings.

    ARCHITECTURE (locked): the brain is a Hermes AGENT, never a backend
    model/LLM client. ``TestLLMProvider`` is the deterministic stub/fallback
    only.

    Modes:
      - ``"stub"`` / ``"test_llm"`` -> the deterministic ``TestLLMProvider``.
      - ``"hybrid"`` (default) -> a ``BrokerReasoningProvider`` that enqueues the
        task for a connected agent/worker, polls ``settings.reasoning_timeout_polls``
        times, then FALLS BACK to ``TestLLMProvider`` so the app always answers.
      - ``"agent_only"`` -> the same broker provider with ``allow_fallback=False``;
        if no agent posts a result it raises ``ReasoningUnavailable`` instead of
        silently using the stub.

    ``fallback`` overrides the default ``TestLLMProvider`` instance (used by the
    broker modes); pass it to share one stub across providers.
    """
    mode = settings.reasoning_mode
    if mode in ("stub", "test_llm"):
        return TestLLMProvider()

    fb = fallback if fallback is not None else TestLLMProvider()
    allow_fallback = mode != "agent_only"
    return BrokerReasoningProvider(
        repo,
        clock,
        fallback=fb,
        timeout_polls=settings.reasoning_timeout_polls,
        allow_fallback=allow_fallback,
        # Only wait for the agent brain when a worker has actually polled recently;
        # otherwise fall back to the stub at once (no multi-second hang per request).
        worker_present=lambda: repo.worker_seen_within(
            clock.now(), settings.worker_presence_seconds
        ),
    )


def build_payment_provider(settings: Settings) -> PaymentProvider:
    """Select the payment provider from Settings.

    Delegates to ``payment.get_payment_provider`` (test_link by default,
    link_cli — dry-run by default — when ``payment_mode == "link_cli"``). No
    real money or network: the live link-cli path is gated inside
    ``LinkCliProvider`` and never auto-executed.
    """
    return get_payment_provider(settings)

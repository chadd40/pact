import os
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI

from pact import factory
from pact.clock import FixedClock
from pact.config import Settings, load_settings
from pact.payment import LinkCliProvider, PaymentProvider, TestLinkProvider
from pact.models import TaskType
from pact.reasoning import (
    BrokerReasoningProvider,
    ReasoningProvider,
    TestLLMProvider,
    make_reasoning_task,
)
from pact.repository import Repository


@pytest.fixture()
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 6, 25, 12, 0, 0, tzinfo=timezone.utc))


@pytest.fixture()
def repo(tmp_path) -> Repository:
    r = Repository.connect(str(tmp_path / "factory.db"))
    r.init_schema()
    yield r
    r.close()


# ── build_reasoning_provider ────────────────────────────────────────────────


def test_stub_mode_returns_test_llm(repo, clock):
    settings = Settings(reasoning_mode="stub")
    provider = factory.build_reasoning_provider(settings, repo, clock)
    assert isinstance(provider, TestLLMProvider)


def test_test_llm_alias_returns_test_llm(repo, clock):
    settings = Settings(reasoning_mode="test_llm")
    provider = factory.build_reasoning_provider(settings, repo, clock)
    assert isinstance(provider, TestLLMProvider)


def test_hybrid_mode_returns_broker_with_fallback(repo, clock):
    settings = Settings(reasoning_mode="hybrid", reasoning_timeout_polls=3)
    provider = factory.build_reasoning_provider(settings, repo, clock)
    assert isinstance(provider, BrokerReasoningProvider)
    assert provider.allow_fallback is True
    assert isinstance(provider.fallback, TestLLMProvider)
    assert provider.timeout_polls == 3
    # The broker still answers (via the fallback) when no worker is connected.
    assert provider.capabilities() == {"text", "vision"}


def test_hybrid_provider_falls_back_when_no_worker_present(repo, clock):
    # Factory wires a worker-presence probe: with a poll budget but NO worker ever
    # seen, resolve must fall back to the stub immediately — no orphan task, no
    # multi-second hang waiting for an agent that isn't serving.
    settings = Settings(reasoning_mode="hybrid", reasoning_timeout_polls=5)
    provider = factory.build_reasoning_provider(settings, repo, clock)
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_nf",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        clock,
    )
    result = provider.resolve(task)
    assert result["status"] == "passed"      # the deterministic stub answered
    assert repo.get_task(task.id) is None     # nothing left orphaned in the broker


def test_hybrid_provider_waits_when_worker_recently_seen(repo, clock):
    # Once a worker has polled (marked seen), the provider enqueues + polls so a
    # serving agent gets first crack. A pre-posted agent result wins over the stub.
    settings = Settings(reasoning_mode="hybrid", reasoning_timeout_polls=2)
    provider = factory.build_reasoning_provider(settings, repo, clock)
    provider.sleep = lambda s: None  # keep the test instant
    repo.mark_worker_seen(clock.now())
    enq = make_reasoning_task(
        TaskType.judge_proof,
        "pact_ws",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        clock,
    )
    from pact.models import TaskStatus

    enq.status = TaskStatus.done
    enq.result = {"status": "passed", "reason": "agent reviewed", "checklist": {}}
    repo.save_task(enq)
    incoming = make_reasoning_task(
        TaskType.judge_proof,
        "pact_ws",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        clock,
    )
    assert provider.resolve(incoming)["reason"] == "agent reviewed"


def test_agent_only_mode_disables_fallback(repo, clock):
    settings = Settings(reasoning_mode="agent_only")
    provider = factory.build_reasoning_provider(settings, repo, clock)
    assert isinstance(provider, BrokerReasoningProvider)
    assert provider.allow_fallback is False
    assert isinstance(provider.fallback, TestLLMProvider)


def test_unknown_mode_defaults_to_hybrid(repo, clock):
    settings = Settings(reasoning_mode="something-else")
    provider = factory.build_reasoning_provider(settings, repo, clock)
    assert isinstance(provider, BrokerReasoningProvider)
    assert provider.allow_fallback is True


def test_explicit_fallback_is_used(repo, clock):
    sentinel = TestLLMProvider()
    settings = Settings(reasoning_mode="hybrid")
    provider = factory.build_reasoning_provider(
        settings, repo, clock, fallback=sentinel
    )
    assert isinstance(provider, BrokerReasoningProvider)
    assert provider.fallback is sentinel


def test_returned_provider_satisfies_protocol(repo, clock):
    for mode in ("stub", "hybrid", "agent_only"):
        provider = factory.build_reasoning_provider(
            Settings(reasoning_mode=mode), repo, clock
        )
        assert isinstance(provider, ReasoningProvider)


# ── build_payment_provider ──────────────────────────────────────────────────


def test_payment_default_is_test_link():
    payment = factory.build_payment_provider(Settings(payment_mode="test_link"))
    assert isinstance(payment, TestLinkProvider)
    assert isinstance(payment, PaymentProvider)


def test_payment_link_cli_selects_link_cli_dry_run():
    settings = Settings(payment_mode="link_cli", link_mode="dry_run")
    payment = factory.build_payment_provider(settings)
    assert isinstance(payment, LinkCliProvider)
    assert payment.link_mode == "dry_run"


def test_payment_link_cli_passes_link_mode_through():
    settings = Settings(payment_mode="link_cli", link_mode="live")
    payment = factory.build_payment_provider(settings)
    assert isinstance(payment, LinkCliProvider)
    assert payment.link_mode == "live"


def test_payment_factory_matches_get_payment_provider():
    from pact.payment import get_payment_provider

    settings = Settings(payment_mode="link_cli", link_mode="dry_run")
    direct = get_payment_provider(settings)
    viafac = factory.build_payment_provider(settings)
    assert type(direct) is type(viafac)


# ── main.build_app wiring (smoke) ───────────────────────────────────────────


def test_build_app_returns_fastapi(tmp_path, monkeypatch):
    # Point at a throwaway DB so the smoke test never touches the repo's default
    # pact.db, and pin to demo clock so no real-time ticker spins up.
    monkeypatch.setenv("PACT_DB_PATH", str(tmp_path / "smoke.db"))
    monkeypatch.setenv("PACT_CLOCK_MODE", "demo")
    import pact.main as main

    app = main.build_app()
    assert isinstance(app, FastAPI)


def test_build_app_uses_factory_for_hybrid(tmp_path, monkeypatch):
    # In hybrid mode build_app must wire a BrokerReasoningProvider (not the bare
    # TestLLMProvider it used to hardcode). We assert via the factory call,
    # capturing the provider it produces.
    monkeypatch.setenv("PACT_DB_PATH", str(tmp_path / "hybrid.db"))
    monkeypatch.setenv("PACT_CLOCK_MODE", "demo")
    monkeypatch.setenv("PACT_REASONING_MODE", "hybrid")
    import pact.main as main

    captured = {}
    real_build = factory.build_reasoning_provider

    def spy(settings, repo, clock, fallback=None):
        provider = real_build(settings, repo, clock, fallback=fallback)
        captured["provider"] = provider
        return provider

    monkeypatch.setattr(main, "build_reasoning_provider", spy)
    app = main.build_app()
    assert isinstance(app, FastAPI)
    assert isinstance(captured["provider"], BrokerReasoningProvider)


def test_build_app_link_cli_payment(tmp_path, monkeypatch):
    monkeypatch.setenv("PACT_DB_PATH", str(tmp_path / "pay.db"))
    monkeypatch.setenv("PACT_CLOCK_MODE", "demo")
    monkeypatch.setenv("PACT_PAYMENT_MODE", "link_cli")
    import pact.main as main

    captured = {}
    real_build = factory.build_payment_provider

    def spy(settings):
        payment = real_build(settings)
        captured["payment"] = payment
        return payment

    monkeypatch.setattr(main, "build_payment_provider", spy)
    app = main.build_app()
    assert isinstance(app, FastAPI)
    assert isinstance(captured["payment"], LinkCliProvider)

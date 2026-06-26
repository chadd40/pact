from __future__ import annotations

import os
from datetime import datetime

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock, RealClock
from pact.config import load_settings
from pact.factory import build_payment_provider, build_reasoning_provider
from pact.repository import Repository


def build_app():
    # Read configuration from the process environment so PACT_CLOCK_MODE=demo (and the
    # other PACT_* knobs) take effect at startup. load_settings() defaults to an empty
    # mapping, so without this the server always runs with the RealClock and the demo
    # advance-day/reset endpoints 409.
    settings = load_settings(os.environ)
    repo = Repository.connect(settings.db_path)
    repo.init_schema()
    if settings.clock_mode == "demo":
        clock = FixedClock(datetime.fromisoformat(settings.demo_seed_iso))
    else:
        clock = RealClock()
    # Config-driven selection (locked: brain is a Hermes agent; TestLLMProvider is
    # only the deterministic stub/fallback). build_reasoning_provider returns the
    # stub directly in stub/test_llm mode and a BrokerReasoningProvider (which
    # enqueues for a connected agent + falls back) in hybrid/agent_only mode.
    provider = build_reasoning_provider(settings, repo, clock)
    payment = build_payment_provider(settings)
    tokens = TokenStore()
    return create_app(repo, provider, payment, tokens, clock, settings)


app = build_app()

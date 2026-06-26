from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Mapping

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock, RealClock
from pact.config import load_settings
from pact.factory import build_payment_provider, build_reasoning_provider
from pact.lifecycle import reconcile_on_startup
from pact.repository import Repository
from pact.scheduler import run_ticker_loop


def build_app(env: Mapping[str, str] | None = None):
    # Read configuration from the process environment so PACT_CLOCK_MODE=demo (and the
    # other PACT_* knobs) take effect at startup. Tests inject a dict instead of os.environ.
    settings = load_settings(os.environ if env is None else env)
    repo = Repository.connect(settings.db_path)
    repo.init_schema()
    if settings.clock_mode == "demo":
        clock = FixedClock(datetime.fromisoformat(settings.demo_seed_iso))
    else:
        clock = RealClock()
    # Config-driven provider/payment selection (locked: the brain is a Hermes AGENT;
    # TestLLMProvider is only the deterministic fallback/stub). build_reasoning_provider
    # returns the stub directly in stub/test_llm mode and a BrokerReasoningProvider
    # (which enqueues for a connected agent + falls back) in hybrid/agent_only mode.
    provider = build_reasoning_provider(settings, repo, clock)
    payment = build_payment_provider(settings)
    tokens = TokenStore()

    @asynccontextmanager
    async def lifespan(app):
        # Startup: one reconciliation sweep so a server restarted mid-pact settles
        # any active pact past its deadline and closes any elapsed dispute window.
        reconcile_on_startup(repo, clock, payment, settings)

        # Autonomous ticker: only on a real-time clock with the scheduler enabled.
        # In demo mode (FixedClock) time is driven by /demo/advance-day, so the
        # real-time ticker must NOT run.
        app.state.ticker_task = None
        app.state.ticker_stop = None
        if settings.scheduler_enabled and isinstance(clock, RealClock):
            stop = asyncio.Event()
            app.state.ticker_stop = stop
            app.state.ticker_task = asyncio.create_task(
                run_ticker_loop(repo, clock, payment, settings, stop=stop)
            )
        try:
            yield
        finally:
            # Shutdown: signal stop and cancel the background ticker if running.
            if app.state.ticker_stop is not None:
                app.state.ticker_stop.set()
            task = app.state.ticker_task
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = create_app(repo, provider, payment, tokens, clock, settings)
    # create_app's signature stays unchanged; we attach the lifespan to the built app.
    app.router.lifespan_context = lifespan
    return app


app = build_app()

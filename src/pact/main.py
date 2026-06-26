from __future__ import annotations

import os
from datetime import datetime

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock, RealClock
from pact.config import load_settings
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def build_app():
    # Read configuration from the process environment so PACT_CLOCK_MODE=demo (and the
    # other PACT_* knobs) take effect at startup. load_settings() defaults to an empty
    # mapping, so without this the server always runs with the RealClock and the demo
    # advance-day/reset endpoints 409.
    settings = load_settings(os.environ)
    repo = Repository.connect(settings.db_path)
    repo.init_schema()
    provider = TestLLMProvider()
    payment = TestLinkProvider()
    tokens = TokenStore()
    if settings.clock_mode == "demo":
        clock = FixedClock(datetime.fromisoformat(settings.demo_seed_iso))
    else:
        clock = RealClock()
    return create_app(repo, provider, payment, tokens, clock, settings)


app = build_app()

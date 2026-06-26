from __future__ import annotations

from datetime import datetime

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock, RealClock
from pact.config import load_settings
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def build_app():
    settings = load_settings()
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

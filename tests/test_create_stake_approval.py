"""Create-time stake approval for the structured (UI) create path.

The new Create flow POSTs /api/pacts/create. Short pacts (Model 1) must pre-authorize
the stake in Link AT CREATION and park at awaiting_stake until the human approves the
spend; /stake/confirm then provisions the card and activates. Long pacts (Model 3) go
active immediately and defer the charge to settlement (the one-time card would expire
before a long pact fails).
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock
from pact.config import Settings
from pact.lifecycle import create_pact_structured
from pact.models import PactStatus
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository

_CHARITY = "against_malaria_foundation"


def _clock() -> FixedClock:
    return FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))


def _build(tmp_path):
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    settings = Settings(db_path=str(tmp_path / "pact.db"), artifacts_dir=str(tmp_path / "artifacts"))
    tokens = TokenStore(ttl_minutes=10)
    app = create_app(repo, TestLLMProvider(), TestLinkProvider(), tokens, _clock(), settings)
    return app, repo, settings


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _mk(*, weeks: int, payment=None, settings: Settings | None = None):
    return create_pact_structured(
        goal_title="Run",
        goal_template=None,
        days_per_week=3,
        weeks=weeks,
        stake_amount_cents=20000,
        charity_id=_CHARITY,
        agent="Hermes",
        consent_acknowledged=True,
        owner="u@example.com",
        clock=_clock(),
        settings=settings or Settings(),
        payment=payment,
    )


# ── Lifecycle unit ───────────────────────────────────────────────────────────


def test_short_pact_with_payment_parks_at_awaiting_stake():
    pact = _mk(weeks=4, payment=TestLinkProvider())
    assert pact.status == PactStatus.awaiting_stake
    assert pact.spend_request_id  # spend-request opened at creation
    assert pact.card_last4 is None  # not provisioned until approval


def test_long_pact_with_payment_goes_active_directly():
    # weeks past the hold ceiling → Model 3: active now, charge at failure.
    pact = _mk(weeks=52, payment=TestLinkProvider())
    assert pact.status == PactStatus.active
    assert pact.spend_request_id is None


def test_no_payment_provider_goes_active():
    pact = _mk(weeks=4, payment=None)
    assert pact.status == PactStatus.active
    assert pact.spend_request_id is None


# ── API endpoint ─────────────────────────────────────────────────────────────


async def _create(client, *, weeks: int):
    return await client.post(
        "/api/pacts/create",
        json={
            "goal_title": "Run",
            "days_per_week": 3,
            "weeks": weeks,
            "stake_amount_cents": 20000,
            "charity_id": _CHARITY,
            "agent": "Hermes",
            "consent_acknowledged": True,
            "owner": "u@example.com",
        },
    )


@pytest.mark.anyio
async def test_api_short_pact_awaits_then_stake_confirm_activates(tmp_path):
    app, repo, _ = _build(tmp_path)
    async with _client(app) as client:
        r = await _create(client, weeks=4)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "awaiting_stake"
        assert body["spend_request_id"]
        assert body["card_last4"] is None

        pid = body["id"]
        c = await client.post(f"/api/pacts/{pid}/stake/confirm")
        assert c.status_code == 200, c.text
        cbody = c.json()
        assert cbody["status"] == "active"
        assert cbody["card_last4"]  # provisioned once approved
        assert repo.get_pact(pid).status == PactStatus.active


@pytest.mark.anyio
async def test_api_long_pact_activates_immediately(tmp_path):
    app, _, _ = _build(tmp_path)
    async with _client(app) as client:
        r = await _create(client, weeks=52)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "active"

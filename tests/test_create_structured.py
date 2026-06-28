"""Tests for the structured pact-creation path (lifecycle unit + API endpoint).

Covers:
- Valid structured create → ACTIVE pact with target_count == days*weeks, deadline ~weeks out
- Over-cap stake ($600 = 60000c) → 422
- Unknown charity → 422
- Non-allowlisted charity URL → not applicable (catalog is always coherent, tested elsewhere)
- Missing consent → 422
- $200 (20000c) stake is accepted (new cap is $10–$500)
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import httpx
import pytest

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock
from pact.config import Settings
from pact.lifecycle import create_pact_structured
from pact.models import PactStatus, StakeState
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


_NOW = datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc)
_CHARITY = "against_malaria_foundation"


def _clock() -> FixedClock:
    return FixedClock(_NOW)


def _settings() -> Settings:
    return Settings()  # new defaults: min=1000, max=50000


def _build(tmp_path):
    clock = _clock()
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    provider = TestLLMProvider()
    payment = TestLinkProvider()
    tokens = TokenStore(ttl_minutes=10)
    settings = _settings()
    app = create_app(repo, provider, payment, tokens, clock, settings)
    return app, repo, clock, settings


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# ── Lifecycle unit tests ─────────────────────────────────────────────────────


def test_lifecycle_valid_structured_create():
    clock = _clock()
    settings = _settings()
    days_per_week = 3
    weeks = 4
    pact = create_pact_structured(
        goal_title="Run 3x per week for a month",
        goal_template=None,
        days_per_week=days_per_week,
        weeks=weeks,
        stake_amount_cents=20000,  # $200 — valid under new cap
        charity_id=_CHARITY,
        agent="Hermes",
        consent_acknowledged=True,
        owner="user@example.com",
        clock=clock,
        settings=settings,
    )
    assert pact.status == PactStatus.active
    assert pact.stake_state == StakeState.committed
    assert pact.target_count == days_per_week * weeks  # 12
    assert pact.stake_amount_cents == 20000
    assert pact.charity_id == _CHARITY
    assert pact.charity_url  # frozen from catalog
    assert pact.agent == "Hermes"
    assert pact.owner == "user@example.com"
    assert pact.title == "Run 3x per week for a month"
    assert pact.distinct_days is True
    assert pact.id.startswith("pact_")
    assert pact.created_at == clock.now()
    assert pact.started_at == clock.now()
    # Deadline should be approximately now + weeks
    expected_deadline = clock.now() + timedelta(weeks=weeks)
    delta = abs((pact.deadline_at - expected_deadline).total_seconds())
    assert delta < 5, f"deadline {pact.deadline_at} not near {expected_deadline}"
    # Rubric sanity
    assert pact.rubric.count_target == pact.target_count
    assert pact.rubric.min_distinct_days <= pact.rubric.count_target


def test_lifecycle_structured_create_rejects_over_cap():
    clock = _clock()
    settings = _settings()
    with pytest.raises(ValueError, match="outside caps"):
        create_pact_structured(
            goal_title="Run",
            goal_template=None,
            days_per_week=3,
            weeks=4,
            stake_amount_cents=60000,  # $600 — over new cap of $500
            charity_id=_CHARITY,
            agent=None,
            consent_acknowledged=True,
            owner="u@example.com",
            clock=clock,
            settings=settings,
        )


def test_lifecycle_structured_create_rejects_below_cap():
    clock = _clock()
    settings = _settings()
    with pytest.raises(ValueError, match="outside caps"):
        create_pact_structured(
            goal_title="Run",
            goal_template=None,
            days_per_week=3,
            weeks=4,
            stake_amount_cents=500,  # $5 — under new min of $10
            charity_id=_CHARITY,
            agent=None,
            consent_acknowledged=True,
            owner="u@example.com",
            clock=clock,
            settings=settings,
        )


def test_lifecycle_structured_create_rejects_unknown_charity():
    clock = _clock()
    settings = _settings()
    with pytest.raises(ValueError, match="unknown charity"):
        create_pact_structured(
            goal_title="Run",
            goal_template=None,
            days_per_week=3,
            weeks=4,
            stake_amount_cents=20000,
            charity_id="not_a_real_charity",
            agent=None,
            consent_acknowledged=True,
            owner="u@example.com",
            clock=clock,
            settings=settings,
        )


def test_lifecycle_structured_create_rejects_missing_consent():
    clock = _clock()
    settings = _settings()
    with pytest.raises(ValueError, match="consent_acknowledged"):
        create_pact_structured(
            goal_title="Run",
            goal_template=None,
            days_per_week=3,
            weeks=4,
            stake_amount_cents=20000,
            charity_id=_CHARITY,
            agent=None,
            consent_acknowledged=False,
            owner="u@example.com",
            clock=clock,
            settings=settings,
        )


def test_lifecycle_200_dollar_stake_accepted():
    """$200 (20000c) must be accepted under the new $10–$500 cap."""
    clock = _clock()
    settings = _settings()
    pact = create_pact_structured(
        goal_title="Exercise daily",
        goal_template="workout",
        days_per_week=5,
        weeks=2,
        stake_amount_cents=20000,
        charity_id=_CHARITY,
        agent="Claude Code",
        consent_acknowledged=True,
        owner="user@example.com",
        clock=clock,
        settings=settings,
    )
    assert pact.stake_amount_cents == 20000
    assert pact.status == PactStatus.active


def test_lifecycle_target_count_equals_days_times_weeks():
    clock = _clock()
    settings = _settings()
    pact = create_pact_structured(
        goal_title="Meditate",
        goal_template=None,
        days_per_week=2,
        weeks=6,
        stake_amount_cents=15000,
        charity_id=_CHARITY,
        agent=None,
        consent_acknowledged=True,
        owner="user@example.com",
        clock=clock,
        settings=settings,
    )
    assert pact.target_count == 2 * 6  # 12


def test_lifecycle_agent_none_stored():
    clock = _clock()
    settings = _settings()
    pact = create_pact_structured(
        goal_title="Study",
        goal_template=None,
        days_per_week=5,
        weeks=4,
        stake_amount_cents=10000,
        charity_id=_CHARITY,
        agent=None,
        consent_acknowledged=True,
        owner="user@example.com",
        clock=clock,
        settings=settings,
    )
    assert pact.agent is None


# ── API endpoint tests ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_api_valid_structured_create(tmp_path):
    app, repo, clock, settings = _build(tmp_path)
    async with _client(app) as client:
        r = await client.post(
            "/api/pacts/create",
            json={
                "goal_title": "Run 3x a week",
                "days_per_week": 3,
                "weeks": 4,
                "stake_amount_cents": 20000,
                "charity_id": _CHARITY,
                "agent": "Hermes",
                "consent_acknowledged": True,
                "owner": "runner@example.com",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "active"
        assert body["stake_state"] == "committed"
        assert body["target_count"] == 12  # 3 * 4
        assert body["stake_amount_cents"] == 20000
        assert body["charity_id"] == _CHARITY
        assert body["agent"] == "Hermes"
        assert body["owner"] == "runner@example.com"
        pact_id = body["id"]
        # Confirm it's persisted
        saved = repo.get_pact(pact_id)
        assert saved is not None
        assert saved.status == PactStatus.active


@pytest.mark.anyio
async def test_api_structured_create_200_dollar_stake_accepted(tmp_path):
    """$200 (20000c) is now within the $10–$500 cap and must succeed."""
    app, repo, clock, settings = _build(tmp_path)
    async with _client(app) as client:
        r = await client.post(
            "/api/pacts/create",
            json={
                "goal_title": "Daily yoga",
                "days_per_week": 5,
                "weeks": 2,
                "stake_amount_cents": 20000,
                "charity_id": _CHARITY,
                "consent_acknowledged": True,
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["stake_amount_cents"] == 20000


@pytest.mark.anyio
async def test_api_structured_create_over_cap_is_422(tmp_path):
    """$600 (60000c) is over the new $500 cap → 422."""
    app, repo, clock, settings = _build(tmp_path)
    async with _client(app) as client:
        r = await client.post(
            "/api/pacts/create",
            json={
                "goal_title": "Run",
                "days_per_week": 3,
                "weeks": 4,
                "stake_amount_cents": 60000,  # $600 — over cap
                "charity_id": _CHARITY,
                "consent_acknowledged": True,
            },
        )
        assert r.status_code == 422, r.text


@pytest.mark.anyio
async def test_api_structured_create_unknown_charity_is_422(tmp_path):
    app, repo, clock, settings = _build(tmp_path)
    async with _client(app) as client:
        r = await client.post(
            "/api/pacts/create",
            json={
                "goal_title": "Run",
                "days_per_week": 3,
                "weeks": 4,
                "stake_amount_cents": 20000,
                "charity_id": "not_a_real_charity",
                "consent_acknowledged": True,
            },
        )
        assert r.status_code == 422, r.text


@pytest.mark.anyio
async def test_api_structured_create_missing_consent_is_422(tmp_path):
    app, repo, clock, settings = _build(tmp_path)
    async with _client(app) as client:
        r = await client.post(
            "/api/pacts/create",
            json={
                "goal_title": "Run",
                "days_per_week": 3,
                "weeks": 4,
                "stake_amount_cents": 20000,
                "charity_id": _CHARITY,
                "consent_acknowledged": False,
            },
        )
        assert r.status_code == 422, r.text


@pytest.mark.anyio
async def test_api_structured_create_consent_omitted_is_422(tmp_path):
    """consent_acknowledged defaults to False when omitted → 422."""
    app, repo, clock, settings = _build(tmp_path)
    async with _client(app) as client:
        r = await client.post(
            "/api/pacts/create",
            json={
                "goal_title": "Run",
                "days_per_week": 3,
                "weeks": 4,
                "stake_amount_cents": 20000,
                "charity_id": _CHARITY,
                # consent_acknowledged not provided
            },
        )
        assert r.status_code == 422, r.text


@pytest.mark.anyio
async def test_api_structured_create_deadline_approx_weeks_out(tmp_path):
    app, repo, clock, settings = _build(tmp_path)
    async with _client(app) as client:
        r = await client.post(
            "/api/pacts/create",
            json={
                "goal_title": "Meditate",
                "days_per_week": 5,
                "weeks": 3,
                "stake_amount_cents": 15000,
                "charity_id": _CHARITY,
                "consent_acknowledged": True,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        from datetime import datetime as dt
        deadline = dt.fromisoformat(body["deadline_at"])
        expected = _NOW + timedelta(weeks=3)
        # Ensure deadline is within a few seconds of expected.
        delta = abs((deadline.replace(tzinfo=timezone.utc) - expected).total_seconds())
        assert delta < 10


@pytest.mark.anyio
async def test_api_structured_create_with_goal_template(tmp_path):
    app, repo, clock, settings = _build(tmp_path)
    async with _client(app) as client:
        r = await client.post(
            "/api/pacts/create",
            json={
                "goal_title": "Morning run",
                "goal_template": "cardio",
                "days_per_week": 4,
                "weeks": 2,
                "stake_amount_cents": 10000,
                "charity_id": _CHARITY,
                "consent_acknowledged": True,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "cardio" in body["goal"]


def test_lifecycle_structured_create_persists_card_art(tmp_path):
    clock, settings = _clock(), _settings()
    pact = create_pact_structured(
        goal_title="Custom goal",
        goal_template=None,
        days_per_week=3,
        weeks=4,
        stake_amount_cents=20000,
        charity_id=_CHARITY,
        agent="Hermes",
        consent_acknowledged=True,
        owner="c@example.com",
        clock=clock,
        settings=settings,
        card_art="/create/create_3.png",
    )
    assert pact.card_art == "/create/create_3.png"


@pytest.mark.anyio
async def test_api_create_persists_card_art(tmp_path):
    app, repo, clock, settings = _build(tmp_path)
    async with _client(app) as client:
        r = await client.post(
            "/api/pacts/create",
            json={
                "goal_title": "Custom goal",
                "days_per_week": 3,
                "weeks": 4,
                "stake_amount_cents": 20000,
                "charity_id": _CHARITY,
                "agent": "Hermes",
                "consent_acknowledged": True,
                "owner": "c@example.com",
                "card_art": "/create/create_2.png",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["card_art"] == "/create/create_2.png"
        assert repo.get_pact(r.json()["id"]).card_art == "/create/create_2.png"


@pytest.mark.anyio
async def test_api_create_card_art_defaults_null(tmp_path):
    app, repo, clock, settings = _build(tmp_path)
    async with _client(app) as client:
        r = await client.post(
            "/api/pacts/create",
            json={
                "goal_title": "Run 3x a week",
                "days_per_week": 3,
                "weeks": 4,
                "stake_amount_cents": 20000,
                "charity_id": _CHARITY,
                "agent": "Hermes",
                "consent_acknowledged": True,
                "owner": "runner@example.com",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["card_art"] is None


@pytest.mark.anyio
async def test_api_create_rejects_unknown_card_art(tmp_path):
    app, repo, clock, settings = _build(tmp_path)
    async with _client(app) as client:
        r = await client.post(
            "/api/pacts/create",
            json={
                "goal_title": "Run",
                "days_per_week": 3,
                "weeks": 4,
                "stake_amount_cents": 20000,
                "charity_id": _CHARITY,
                "agent": "Hermes",
                "consent_acknowledged": True,
                "owner": "c@example.com",
                "card_art": "/evil.png",
            },
        )
        assert r.status_code == 422, r.text

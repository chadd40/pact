"""Nag-until-resolved: the miss records at finalization regardless of payment,
the agent nags an unresolved donation, and the owner can explicitly decline."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock
from pact.config import Settings
from pact.models import Modality, Pact, PactStatus, Rubric, StakeState
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository

OWNER = "demo@pact.local"


class _SpyPayment:
    def __init__(self):
        self.calls = 0
        self._inner = TestLinkProvider()

    def create_donation(self, pact, idempotency_key):
        self.calls += 1
        return self._inner.create_donation(pact, idempotency_key)


def _build(tmp_path, clock):
    db = str(tmp_path / "p.db")
    repo = Repository.connect(db)
    repo.init_schema()
    payment = _SpyPayment()
    app = create_app(repo, TestLLMProvider(), payment, TokenStore(), clock, Settings(db_path=db))
    return app, repo, payment


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _failing_pact(clock) -> Pact:
    now = clock.now()
    return Pact(
        id="pact_miss",
        owner=OWNER,
        original_prompt="do the thing 5x or $20 to charity",
        title="Do the thing",
        goal="Complete the thing on 5 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=now + timedelta(days=1),
        target_count=5,
        recommended_stake_cents=2000,
        stake_amount_cents=2000,
        charity_id="against_malaria_foundation",
        charity_url="https://againstmalaria.com/donate",
        rubric=Rubric(modality=Modality.photo, must_show=["x"], min_distinct_days=5, count_target=5),
        status=PactStatus.active,
        stake_state=StakeState.committed,
        created_at=now,
        started_at=now,
    )


@pytest.mark.asyncio
async def test_miss_records_at_finalization_even_with_link_unconnected(tmp_path):
    clock = FixedClock(datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc))
    app, repo, payment = _build(tmp_path, clock)
    repo.save_pact(_failing_pact(clock))

    async with _client(app) as client:
        clock.advance(days=2)  # past deadline
        await client.post("/api/pacts/pact_miss/settle")  # -> failed, window opens
        # Profile NOT recorded yet (window open, overturn still possible).
        prof = (await client.get("/api/profile", params={"owner": OWNER})).json()
        assert prof["failed"] == 0

        clock.advance(days=5)  # past the dispute window; Link NOT connected
        await client.post("/api/pacts/pact_miss/settle")  # -> donation_pending (deferred)
        p = (await client.get("/api/pacts/pact_miss")).json()
        assert p["status"] == "donation_pending"
        assert payment.calls == 0  # no money moved

        # The miss + streak loss are recorded NOW, at finalization, regardless.
        prof = (await client.get("/api/profile", params={"owner": OWNER})).json()
        assert prof["failed"] == 1
        assert prof["current_streak"] == 0


@pytest.mark.asyncio
async def test_owner_can_explicitly_decline_pending_donation(tmp_path):
    clock = FixedClock(datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc))
    app, repo, payment = _build(tmp_path, clock)
    repo.save_pact(_failing_pact(clock))

    async with _client(app) as client:
        clock.advance(days=2)
        await client.post("/api/pacts/pact_miss/settle")
        clock.advance(days=5)
        await client.post("/api/pacts/pact_miss/settle")  # donation_pending

        r = await client.post("/api/pacts/pact_miss/decline")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "donation_declined"
        assert payment.calls == 0  # declining moves no money

        # Still exactly one failure (idempotent with the finalization record).
        prof = (await client.get("/api/profile", params={"owner": OWNER})).json()
        assert prof["failed"] == 1

    # Decline is only valid from donation_pending.
    async with _client(app) as client:
        r = await client.post("/api/pacts/pact_miss/decline")  # already declined -> idempotent ok
        assert r.json()["status"] == "donation_declined"


@pytest.mark.asyncio
async def test_tick_nags_unresolved_donation_without_piling_up(tmp_path):
    clock = FixedClock(datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc))
    app, repo, payment = _build(tmp_path, clock)
    repo.save_pact(_failing_pact(clock))

    async with _client(app) as client:
        clock.advance(days=2)
        await client.post("/api/pacts/pact_miss/settle")
        clock.advance(days=5)
        await client.post("/api/pacts/pact_miss/settle")  # donation_pending

        # First tick queues exactly one donation nag.
        r1 = await client.post("/api/tick")
        assert "pact_miss" in r1.json()["nagged"]
        thread = (await client.get("/api/pacts/pact_miss/coach")).json()
        nags = [m for m in thread if m["trigger"] == "donation_pending"]
        assert len(nags) == 1

        # A second tick does NOT pile up (the nag is still undelivered).
        r2 = await client.post("/api/tick")
        assert "pact_miss" not in r2.json()["nagged"]
        thread = (await client.get("/api/pacts/pact_miss/coach")).json()
        assert len([m for m in thread if m["trigger"] == "donation_pending"]) == 1

from datetime import datetime, timezone

from pact.clock import FixedClock
from pact.link import connect_account, new_account


def _clock() -> FixedClock:
    return FixedClock(datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc))


def test_new_account_defaults_disconnected():
    acct = new_account("a@b.com")
    assert acct.owner == "a@b.com"
    assert acct.connected is False
    assert acct.funding_ref is None
    assert acct.connected_at is None


def test_connect_sets_connected_and_funding_ref():
    clock = _clock()
    acct = connect_account(new_account("a@b.com"), clock)
    assert acct.connected is True
    assert acct.funding_ref == "test_funding_a@b.com"
    assert acct.connected_at == clock.now()


def test_connect_is_idempotent():
    clock = _clock()
    once = connect_account(new_account("a@b.com"), clock)
    later = FixedClock(datetime(2026, 7, 1, tzinfo=timezone.utc))
    twice = connect_account(once, later)
    # Re-connecting changes nothing (keeps the original connected_at).
    assert twice.connected_at == clock.now()
    assert twice.funding_ref == "test_funding_a@b.com"


def test_repo_round_trips_link_account(tmp_path):
    from pact.repository import Repository

    repo = Repository.connect(str(tmp_path / "p.db"))
    repo.init_schema()
    assert repo.get_link_account("a@b.com") is None
    repo.save_link_account(connect_account(new_account("a@b.com"), _clock()))
    got = repo.get_link_account("a@b.com")
    assert got is not None and got.connected is True
    assert got.funding_ref == "test_funding_a@b.com"


# ── API + settlement-gate tests ──────────────────────────────────────────────

import httpx  # noqa: E402
import pytest  # noqa: E402

from pact.anticheat import TokenStore  # noqa: E402
from pact.api import create_app  # noqa: E402
from pact.config import Settings  # noqa: E402
from pact.models import (  # noqa: E402
    Modality,
    Pact,
    PactStatus,
    Rubric,
    StakeState,
)
from pact.payment import TestLinkProvider  # noqa: E402
from pact.reasoning import TestLLMProvider  # noqa: E402
from pact.repository import Repository  # noqa: E402
from datetime import timedelta  # noqa: E402


class _SpyPayment:
    def __init__(self):
        self.calls = 0
        self._inner = TestLinkProvider()

    def create_donation(self, pact, idempotency_key):
        self.calls += 1
        return self._inner.create_donation(pact, idempotency_key)


def _build(tmp_path, clock, payment=None):
    db = str(tmp_path / "p.db")
    repo = Repository.connect(db)
    repo.init_schema()
    settings = Settings(db_path=db)
    payment = payment or _SpyPayment()
    app = create_app(repo, TestLLMProvider(), payment, TokenStore(), clock, settings)
    return app, repo, payment


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _failing_pact(clock, owner: str) -> Pact:
    now = clock.now()
    return Pact(
        id="pact_gate1",
        owner=owner,
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
async def test_link_status_then_connect(tmp_path):
    clock = _clock()
    app, _, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        r = await client.get("/api/link/status", params={"owner": "a@b.com"})
        assert r.json() == {"owner": "a@b.com", "connected": False, "funding_ref": None}

        r = await client.post("/api/link/connect", json={"owner": "a@b.com"})
        assert r.status_code == 200, r.text
        assert r.json()["connected"] is True
        assert r.json()["funding_ref"] == "test_funding_a@b.com"

        r = await client.get("/api/link/status", params={"owner": "a@b.com"})
        assert r.json()["connected"] is True


@pytest.mark.asyncio
async def test_settlement_is_gated_on_link_connection(tmp_path):
    owner = "a@b.com"
    clock = _clock()
    app, repo, payment = _build(tmp_path, clock)
    repo.save_pact(_failing_pact(clock, owner))

    async with _client(app) as client:
        # Cross the deadline → settle → failed, dispute window opens, no money.
        clock.advance(days=2)
        r = await client.post("/api/pacts/pact_gate1/settle")
        assert r.json()["status"] == "failed"
        assert payment.calls == 0

        # Cross the dispute window → settle, but Link is NOT connected → deferred.
        clock.advance(days=5)
        await client.post("/api/pacts/pact_gate1/settle")
        assert payment.calls == 0
        p = await client.get("/api/pacts/pact_gate1")
        assert p.json()["status"] == "donation_pending"

        # Connect Link → settle again → the deferred donation fires exactly once.
        await client.post("/api/link/connect", json={"owner": owner})
        await client.post("/api/pacts/pact_gate1/settle")
        assert payment.calls == 1
        p = await client.get("/api/pacts/pact_gate1")
        assert p.json()["status"] == "donated"

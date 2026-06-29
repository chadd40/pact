"""End-to-end: the spend-policy endpoints and the deterministic spend gate wired
into settlement. Proves a low agent spend limit blocks a real donation through
the API, and raising it lets the donation fire."""

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

OWNER = "owner@example.com"
NOW = datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc)


def _build(tmp_path):
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    clock = FixedClock(NOW)
    settings = Settings(db_path=str(tmp_path / "pact.db"))
    app = create_app(
        repo, TestLLMProvider(), TestLinkProvider(), TokenStore(), clock, settings
    )
    return app, repo


def _failed_pact(pid: str, stake_cents: int) -> Pact:
    """A pact already failed with its dispute window closed in the past — the
    exact state /settle turns into a donation via close_dispute_window."""
    return Pact(
        id=pid,
        owner=OWNER,
        original_prompt="do the thing 3x",
        title="Do the thing",
        goal="Complete the thing on 3 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=NOW - timedelta(days=2),
        target_count=3,
        distinct_days=True,
        recommended_stake_cents=stake_cents,
        stake_amount_cents=stake_cents,
        charity_id="against_malaria_foundation",
        charity_url="https://againstmalaria.com/donate",
        rubric=Rubric(
            modality=Modality.photo,
            must_show=["evidence"],
            min_distinct_days=3,
            count_target=3,
        ),
        status=PactStatus.failed,
        stake_state=StakeState.committed,
        created_at=NOW - timedelta(days=9),
        started_at=NOW - timedelta(days=9),
        verdict_at=NOW - timedelta(days=1),
        dispute_window_closes_at=NOW - timedelta(hours=1),
    )


@pytest.mark.asyncio
async def test_policy_roundtrip_and_spend_gate(tmp_path):
    app, repo = _build(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Connect a (test) funding source so a charge CAN fire.
        r = await client.post("/api/link/connect", json={"owner": OWNER})
        assert r.status_code == 200, r.text

        # Set the agent spend limit to $1.00 and read it back.
        r = await client.post(
            "/api/policy", json={"owner": OWNER, "spend_limit_cents": 100}
        )
        assert r.status_code == 200, r.text
        assert r.json()["spend_limit_cents"] == 100
        assert r.json()["rail"] == "spend_policy"  # deterministic gate

        r = await client.get("/api/policy", params={"owner": OWNER})
        assert r.json()["spend_limit_cents"] == 100
        assert "against_malaria_foundation" in r.json()["charity_allowlist"]

        # A $5 stake exceeds the $1 limit → the spend gate blocks the donation.
        repo.save_pact(_failed_pact("pact_block", 500))
        r = await client.post("/api/pacts/pact_block/settle")
        assert r.status_code == 200, r.text
        blocked = (await client.get("/api/pacts/pact_block")).json()
        assert blocked["status"] == "donation_declined"
        assert blocked["stake_state"] == "declined"
        assert blocked["spend_request_id"] is None

        # Raise the limit to $10 → a $5 stake now passes the gate and donates.
        r = await client.post(
            "/api/policy", json={"owner": OWNER, "spend_limit_cents": 1000}
        )
        assert r.status_code == 200, r.text
        repo.save_pact(_failed_pact("pact_ok", 500))
        r = await client.post("/api/pacts/pact_ok/settle")
        assert r.status_code == 200, r.text
        ok = (await client.get("/api/pacts/pact_ok")).json()
        assert ok["status"] == "donated"
        assert ok["spend_request_id"]

"""API: provision the virtual card for an approved donation.

Returns only non-secret metadata; stores last4 + the server-side card file path
on the pact so the Stripe-Checkout helper (Tier 2) can complete the donation.
"""

import json
import os
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
    settings = Settings(
        db_path=str(tmp_path / "pact.db"),
        artifacts_dir=str(tmp_path / "artifacts"),
    )
    app = create_app(
        repo, TestLLMProvider(), TestLinkProvider(), TokenStore(), clock, settings
    )
    return app, repo, settings


def _donated_pact(pid: str) -> Pact:
    return Pact(
        id=pid,
        owner=OWNER,
        original_prompt="do the thing",
        title="Do the thing",
        goal="Complete it.",
        timezone="America/Los_Angeles",
        deadline_at=NOW - timedelta(days=2),
        target_count=3,
        recommended_stake_cents=2000,
        stake_amount_cents=2000,
        charity_id="against_malaria_foundation",
        charity_url="https://againstmalaria.com/donate",
        rubric=Rubric(modality=Modality.photo, must_show=["x"], min_distinct_days=3, count_target=3),
        status=PactStatus.donated,
        stake_state=StakeState.executed,
        spend_request_id="test_sr_donated_2000",
        created_at=NOW - timedelta(days=9),
        started_at=NOW - timedelta(days=9),
        verdict_at=NOW - timedelta(days=1),
    )


@pytest.mark.asyncio
async def test_provision_card_returns_metadata_and_stores_on_pact(tmp_path):
    app, repo, settings = _build(tmp_path)
    repo.save_pact(_donated_pact("pact_card"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/pacts/pact_card/donation/card")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["provisioned"] is True
        assert body["last4"] == "4242"
        # PAN must not be in the API response
        assert "4242424242424242" not in r.text
        assert "number" not in body

    # last4 + server-side card path persisted; the card file exists on disk
    pact = repo.get_pact("pact_card")
    assert pact.card_last4 == "4242"
    assert pact.card_artifact_path and os.path.exists(pact.card_artifact_path)
    data = json.loads(open(pact.card_artifact_path).read())
    assert data["card"]["last4"] == "4242"


@pytest.mark.asyncio
async def test_provision_card_requires_a_spend_request(tmp_path):
    app, repo, _ = _build(tmp_path)
    p = _donated_pact("pact_nosr")
    p.spend_request_id = None
    repo.save_pact(p)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/pacts/pact_nosr/donation/card")
        assert r.status_code == 409


def _write_card_file(path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "card": {
                    "number": "4242424242424242",
                    "cvc": "123",
                    "exp_month": 12,
                    "exp_year": 2030,
                    "last4": "4242",
                    "brand": "visa",
                },
                "mode": "test",
            },
            fh,
        )


@pytest.mark.asyncio
async def test_card_credential_returns_the_secret_for_agent_side_crawl(tmp_path):
    # Agent-side crawl: the owner's agent needs the full card (PAN/CVC) to pay on an
    # arbitrary charity's donate page. The single-use, merchant-locked card is returned
    # to the authorized caller (this deliberately exposes the PAN — see the endpoint).
    app, repo, _ = _build(tmp_path)
    card_file = str(tmp_path / "card.json")
    _write_card_file(card_file)
    pact = _donated_pact("pact_cred")
    pact.card_artifact_path = card_file
    pact.card_last4 = "4242"
    repo.save_pact(pact)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/pacts/pact_cred/donation/card-credential")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["number"] == "4242424242424242"
        assert body["cvc"] == "123"
        assert body["exp_month"] == 12
        assert body["exp_year"] == 2030
        assert body["last4"] == "4242"


@pytest.mark.asyncio
async def test_card_credential_requires_a_provisioned_card(tmp_path):
    app, repo, _ = _build(tmp_path)
    repo.save_pact(_donated_pact("pact_nocred"))  # no card_artifact_path
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/pacts/pact_nocred/donation/card-credential")
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_card_credential_is_owner_scoped_when_authed(tmp_path):
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    clock = FixedClock(NOW)
    settings = Settings(
        db_path=str(tmp_path / "pact.db"),
        artifacts_dir=str(tmp_path / "artifacts"),
        auth_mode="agent_token",
    )
    app = create_app(repo, TestLLMProvider(), TestLinkProvider(), TokenStore(), clock, settings)
    card_file = str(tmp_path / "card.json")
    _write_card_file(card_file)
    pact = _donated_pact("pact_scoped")
    pact.card_artifact_path = card_file
    repo.save_pact(pact)
    from pact.accounts import issue_token

    other_session, other_token = issue_token("intruder@example.com", clock, scopes=["claim_tasks"])
    repo.save_account_link(other_session)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # A token for a different owner must not be able to pull this card's secret.
        r = await client.post(
            "/api/pacts/pact_scoped/donation/card-credential",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_live_card_requires_human_approval_not_just_pending(tmp_path):
    # Live two-phase: the spend request is opened at initiate (donation_pending,
    # pre-approval). A card carries real charge authority, so it must NOT be
    # provisionable until the human has actually approved (status donated).
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    clock = FixedClock(NOW)
    settings = Settings(
        db_path=str(tmp_path / "pact.db"),
        artifacts_dir=str(tmp_path / "artifacts"),
        payment_mode="link_cli",
        link_mode="live",
    )
    app = create_app(repo, TestLLMProvider(), TestLinkProvider(), TokenStore(), clock, settings)
    pending = _donated_pact("pact_pending").model_copy(
        update={"status": PactStatus.donation_pending, "stake_state": StakeState.executing}
    )
    repo.save_pact(pending)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/pacts/pact_pending/donation/card")
        assert r.status_code == 409

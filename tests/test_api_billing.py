"""T1: billing profile captured at onboarding (name + address) for charity-form filling."""
import httpx
import pytest
from datetime import datetime, timezone

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock
from pact.config import Settings
from pact.models import Profile
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def _build(tmp_path):
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    settings = Settings(db_path=str(tmp_path / "pact.db"), artifacts_dir=str(tmp_path / "artifacts"))
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app = create_app(repo, TestLLMProvider(), TestLinkProvider(), TokenStore(), clock, settings)
    return app, repo


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_billing_set_and_get_round_trip(tmp_path):
    app, _ = _build(tmp_path)
    async with _client(app) as c:
        body = {
            "owner": "demo@pact.local", "first_name": "Ada", "last_name": "Lovelace",
            "email": "ada@example.com", "street": "1 Analytical Way", "city": "London",
            "state": "", "postal_code": "EC1A 1AA", "country": "GB",
        }
        r = await c.post("/api/account/billing", json=body)
        assert r.status_code == 200, r.text
        r = await c.get("/api/account/billing", params={"owner": "demo@pact.local"})
        assert r.status_code == 200, r.text
        got = r.json()
        assert got["first_name"] == "Ada" and got["last_name"] == "Lovelace"
        assert got["street"] == "1 Analytical Way" and got["postal_code"] == "EC1A 1AA"
        assert got["country"] == "GB" and got["email"] == "ada@example.com"


def _seed_donation_pending_pact(repo, tmp_path, owner="demo@pact.local"):
    from pact.models import Modality, Pact, PactStatus, Rubric, StakeState
    cred = TestLinkProvider().retrieve_card("sr_seed", output_dir=str(tmp_path / "cards"))
    pact = Pact(
        id="pact_billing_seed", owner=owner, original_prompt="x", title="t", goal="g",
        timezone="America/Los_Angeles", deadline_at=datetime(2026, 6, 28, tzinfo=timezone.utc),
        target_count=5, recommended_stake_cents=2000, stake_amount_cents=2000,
        charity_id="against_malaria_foundation", charity_url="https://againstmalaria.com/donate",
        rubric=Rubric(modality=Modality.photo, must_show=["x"], min_distinct_days=5, count_target=5),
        status=PactStatus.donation_pending, stake_state=StakeState.committed,
        spend_request_id="sr_seed", card_last4="4242", card_artifact_path=cred.card_file,
        created_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
    )
    repo.save_pact(pact)
    return pact


@pytest.mark.asyncio
async def test_card_credential_includes_billing_for_the_agent(tmp_path):
    # The agent fills the charity form with the card AND the user's billing info, so
    # the card-credential response must carry both (Link has no billing fields).
    app, repo = _build(tmp_path)
    async with _client(app) as c:
        await c.post("/api/account/billing", json={
            "owner": "demo@pact.local", "first_name": "Ada", "last_name": "Lovelace",
            "street": "1 Analytical Way", "city": "London", "postal_code": "EC1A 1AA", "country": "GB",
        })
        pact = _seed_donation_pending_pact(repo, tmp_path)
        r = await c.post(f"/api/pacts/{pact.id}/donation/card-credential")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["number"]  # card fields stay at top level (back-compat)
        assert body["billing"]["first_name"] == "Ada"
        assert body["billing"]["last_name"] == "Lovelace"
        assert body["billing"]["postal_code"] == "EC1A 1AA"


@pytest.mark.asyncio
async def test_billing_preserves_other_profile_fields(tmp_path):
    app, repo = _build(tmp_path)
    async with _client(app) as c:
        repo.save_profile(Profile(owner="demo@pact.local", current_streak=3, spend_limit_cents=5000))
        r = await c.post("/api/account/billing", json={"owner": "demo@pact.local", "first_name": "Ada"})
        assert r.status_code == 200, r.text
        prof = repo.get_profile("demo@pact.local")
        assert prof.current_streak == 3 and prof.spend_limit_cents == 5000  # preserved
        assert prof.first_name == "Ada"

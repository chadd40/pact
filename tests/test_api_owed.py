"""T6: owed-pacts surface — the serving agent finds donation_pending pacts to pay."""
import httpx
import pytest
from datetime import datetime, timezone

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock
from pact.config import Settings
from pact.models import Modality, Pact, PactStatus, Rubric, StakeState
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def _build(tmp_path):
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    settings = Settings(db_path=str(tmp_path / "pact.db"))
    app = create_app(repo, TestLLMProvider(), TestLinkProvider(), TokenStore(),
                     FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc)), settings)
    return app, repo


def _pact(pid, owner, status):
    return Pact(
        id=pid, owner=owner, original_prompt="x", title="t", goal="g",
        timezone="America/Los_Angeles", deadline_at=datetime(2026, 6, 28, tzinfo=timezone.utc),
        target_count=5, recommended_stake_cents=2000, stake_amount_cents=2000,
        charity_id="against_malaria_foundation", charity_url="https://againstmalaria.com/donate",
        rubric=Rubric(modality=Modality.photo, must_show=["x"], min_distinct_days=5, count_target=5),
        status=status, stake_state=StakeState.committed, created_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_owed_returns_only_donation_pending_for_owner(tmp_path):
    app, repo = _build(tmp_path)
    repo.save_pact(_pact("owed1", "me@x.com", PactStatus.donation_pending))
    repo.save_pact(_pact("active1", "me@x.com", PactStatus.active))
    repo.save_pact(_pact("done1", "me@x.com", PactStatus.donation_complete))
    repo.save_pact(_pact("owed_other", "other@x.com", PactStatus.donation_pending))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/account/owed", params={"owner": "me@x.com"})
        assert r.status_code == 200, r.text
        ids = {p["id"] for p in r.json()}
        assert ids == {"owed1"}  # only this owner's donation_pending

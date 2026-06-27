from datetime import datetime, timezone

import httpx
import pytest

from pact.accounts import link_for, mint_token
from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock
from pact.config import Settings
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def test_mint_token_is_deterministic_per_owner():
    assert mint_token("a@b.com") == mint_token("a@b.com")
    assert mint_token("a@b.com") != mint_token("c@d.com")
    assert mint_token("a@b.com").startswith("pat_")


def test_repo_round_trips_account_link(tmp_path):
    repo = Repository.connect(str(tmp_path / "p.db"))
    repo.init_schema()
    clock = FixedClock(datetime(2026, 6, 26, tzinfo=timezone.utc))
    link = link_for("a@b.com", clock)
    repo.save_account_link(link)
    assert repo.get_account_link("a@b.com").token == link.token
    assert repo.owner_for_token(link.token) == "a@b.com"
    assert repo.owner_for_token("pat_nope") is None


def _build(tmp_path):
    db = str(tmp_path / "p.db")
    repo = Repository.connect(db)
    repo.init_schema()
    clock = FixedClock(datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc))
    return create_app(repo, TestLLMProvider(), TestLinkProvider(), TokenStore(), clock, Settings(db_path=db))


@pytest.mark.asyncio
async def test_mint_then_resolve_agent_token(tmp_path):
    app = _build(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/account/agent-token", json={"owner": "a@b.com"})
        assert r.status_code == 200, r.text
        token = r.json()["token"]
        assert token.startswith("pat_")

        r = await client.get("/api/account/resolve", params={"token": token})
        assert r.status_code == 200
        assert r.json()["owner"] == "a@b.com"

        r = await client.get("/api/account/resolve", params={"token": "pat_unknown"})
        assert r.status_code == 404

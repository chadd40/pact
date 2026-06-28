from datetime import datetime, timezone

import httpx
import pytest

from pact.accounts import hash_token, issue_token, link_for, token_prefix, verify_token
from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock
from pact.config import Settings
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def test_issue_token_is_random_and_stores_only_hash():
    clock = FixedClock(datetime(2026, 6, 26, tzinfo=timezone.utc))
    first, first_raw = issue_token("a@b.com", clock)
    second, second_raw = issue_token("a@b.com", clock)

    assert first_raw != second_raw
    assert first_raw.startswith("pat_")
    assert first.token_hash == hash_token(first_raw)
    assert first.token_prefix == token_prefix(first_raw)
    assert first_raw not in first.model_dump_json()
    assert second_raw not in second.model_dump_json()
    assert verify_token(first_raw, first) is True
    assert verify_token(second_raw, first) is False


def test_repo_round_trips_account_link(tmp_path):
    repo = Repository.connect(str(tmp_path / "p.db"))
    repo.init_schema()
    clock = FixedClock(datetime(2026, 6, 26, tzinfo=timezone.utc))
    link, raw = link_for("a@b.com", clock)
    repo.save_account_link(link)
    assert repo.get_account_link("a@b.com").token_hash == link.token_hash
    assert repo.owner_for_token_hash(hash_token(raw)) == "a@b.com"
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
        assert r.json()["token_prefix"] == token_prefix(token)

        stored = app.state.repo.get_account_link("a@b.com")
        assert stored is not None
        assert stored.token_hash == hash_token(token)
        assert token not in stored.model_dump_json()

        r = await client.get("/api/account/resolve", params={"token": token})
        assert r.status_code == 200
        assert r.json()["owner"] == "a@b.com"
        assert r.json()["token_prefix"] == token_prefix(token)

        r = await client.get("/api/account/resolve", params={"token": "pat_unknown"})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_revoked_agent_token_no_longer_resolves(tmp_path):
    app = _build(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        minted = await client.post("/api/account/agent-token", json={"owner": "a@b.com"})
        token = minted.json()["token"]

        r = await client.post("/api/account/revoke-token", json={"owner": "a@b.com"})
        assert r.status_code == 200, r.text
        assert r.json()["revoked"] is True

        r = await client.get("/api/account/resolve", params={"token": token})
        assert r.status_code == 404

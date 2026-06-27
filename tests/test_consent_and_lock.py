from __future__ import annotations

import os
import tempfile
import threading
from datetime import datetime, timezone

import httpx
import pytest

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock
from pact.config import Settings
from pact.lifecycle import confirm_and_start, draft_pact
from pact.models import CoachingMessage, Modality, Pact, PactStatus, Rubric, StakeState
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def _clock() -> FixedClock:
    return FixedClock(datetime(2026, 6, 24, 18, 0, 0, tzinfo=timezone.utc))


def _settings(tmp_path=None) -> Settings:
    if tmp_path is not None:
        return Settings(db_path=str(tmp_path / "pact.db"))
    return Settings()


def _build(tmp_path):
    clock = _clock()
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    provider = TestLLMProvider()
    payment = TestLinkProvider()
    tokens = TokenStore(ttl_minutes=10)
    settings = _settings(tmp_path)
    app = create_app(repo, provider, payment, tokens, clock, settings)
    return app, repo, clock, settings, provider


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# ── (a) lifecycle-level consent guard ───────────────────────────────────────


def test_confirm_and_start_requires_consent():
    clock = _clock()
    settings = Settings()
    provider = TestLLMProvider()
    pact = draft_pact("work out 5x this week or $20 to charity", provider, clock, settings)

    # No acknowledgment (default False) -> refuse to start.
    with pytest.raises(ValueError):
        confirm_and_start(pact, 1000, "against_malaria_foundation", clock, settings)

    # Explicit False -> still refused.
    with pytest.raises(ValueError):
        confirm_and_start(
            pact, 1000, "against_malaria_foundation", clock, settings,
            consent_acknowledged=False,
        )


def test_confirm_and_start_with_consent_activates():
    clock = _clock()
    settings = Settings()
    provider = TestLLMProvider()
    pact = draft_pact("work out 5x this week or $20 to charity", provider, clock, settings)

    started = confirm_and_start(
        pact, 1000, "against_malaria_foundation", clock, settings,
        consent_acknowledged=True,
    )
    assert started.status == PactStatus.active
    assert started.stake_state == StakeState.committed
    assert started.stake_amount_cents == 1000


# ── (a) API-level consent guard ─────────────────────────────────────────────


@pytest.mark.anyio
async def test_api_confirm_without_consent_is_422(tmp_path):
    app, repo, clock, settings, provider = _build(tmp_path)
    async with _client(app) as client:
        r = await client.post(
            "/api/pacts/draft",
            json={"prompt": "work out 5x this week or $20 to charity"},
        )
        assert r.status_code == 200, r.text
        pact_id = r.json()["id"]

        # consent omitted -> default False -> 422
        r = await client.post(
            "/api/pacts",
            json={
                "pact_id": pact_id,
                "stake_amount_cents": 1500,
                "charity_id": "against_malaria_foundation",
            },
        )
        assert r.status_code == 422, r.text

        # still draft — nothing started
        r = await client.get(f"/api/pacts/{pact_id}")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "draft"


@pytest.mark.anyio
async def test_api_confirm_with_consent_activates(tmp_path):
    app, repo, clock, settings, provider = _build(tmp_path)
    async with _client(app) as client:
        r = await client.post(
            "/api/pacts/draft",
            json={"prompt": "work out 5x this week or $20 to charity"},
        )
        assert r.status_code == 200, r.text
        pact_id = r.json()["id"]

        r = await client.post(
            "/api/pacts",
            json={
                "pact_id": pact_id,
                "stake_amount_cents": 1500,
                "charity_id": "against_malaria_foundation",
                "consent_acknowledged": True,
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "active"
        assert r.json()["stake_amount_cents"] == 1500


# ── (b) repository write-lock under concurrency ─────────────────────────────


def _pact(idx: int) -> Pact:
    now = datetime(2026, 6, 24, 18, 0, 0, tzinfo=timezone.utc)
    return Pact(
        id=f"pact-conc-{idx}",
        owner="owner@example.com",
        original_prompt="x",
        title=f"Pact {idx}",
        goal="g",
        timezone="America/Los_Angeles",
        deadline_at=now,
        target_count=5,
        recommended_stake_cents=500,
        stake_amount_cents=500,
        charity_id="against_malaria_foundation",
        charity_url="https://againstmalaria.com/donate",
        rubric=Rubric(
            modality=Modality.photo,
            require_token=True,
            must_show=["evidence"],
            reject_if=["stock"],
            min_distinct_days=5,
            count_target=5,
        ),
        status=PactStatus.active,
        stake_state=StakeState.committed,
        created_at=now,
        started_at=now,
    )


def test_repository_has_write_lock():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        repo = Repository.connect(path)
        # A reentrant guard lock must exist on the repository instance. It now
        # serializes ALL connection access (reads + writes) so parallel reads
        # from FastAPI's threadpool can't race the shared sqlite cursor.
        assert isinstance(repo._write_lock, type(threading.RLock()))
    finally:
        os.remove(path)


def test_concurrent_writes_do_not_corrupt():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        repo = Repository.connect(path)
        repo.init_schema()

        errors: list[BaseException] = []
        n = 40

        def worker(i: int) -> None:
            try:
                repo.save_pact(_pact(i))
                msg = CoachingMessage(
                    id=f"cm-conc-{i}",
                    pact_id=f"pact-conc-{i}",
                    direction="outbound",
                    trigger="mid_week",
                    body="keep going",
                    sent_at=datetime(2026, 6, 24, 18, 0, 0, tzinfo=timezone.utc),
                )
                repo.save_coaching_message(msg)
            except BaseException as exc:  # noqa: BLE001 - capture for assertion
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"concurrent writes raised: {errors!r}"
        # Every row landed: no lost/half-written writes.
        assert len(repo.list_pacts()) == n
        for i in range(n):
            assert repo.get_pact(f"pact-conc-{i}") is not None
            assert repo.get_coaching_message(f"cm-conc-{i}") is not None
    finally:
        os.remove(path)

"""Backend tests for the app-shell redesign:
- Pact stores days_per_week + weeks (cadence source of truth)
- progress.compute_cadence derives the "N days a week · week X of Y · this week k/N" read-model
- the two-phase Link donation flow (initiate → awaiting_approval → approve → donated, single-fire) + decline
- seed_states builds every Detail state for the demo
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from pact.anticheat import TokenStore, day_bucket
from pact.api import create_app
from pact.clock import FixedClock
from pact.config import Settings, load_settings
from pact.demo import _showcase_pact, seed, seed_states
from pact.lifecycle import create_pact_structured
from pact.models import (
    Modality,
    Pact,
    PactStatus,
    Proof,
    ProofStatus,
    Rubric,
    StakeState,
)
from pact.progress import compute_cadence, derive_cadence
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository

_NOW = datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc)
_CHARITY = "against_malaria_foundation"


def _clock() -> FixedClock:
    return FixedClock(_NOW)


def _build(tmp_path):
    clock = _clock()
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    app = create_app(
        repo, TestLLMProvider(), TestLinkProvider(), TokenStore(ttl_minutes=10),
        clock, Settings(),
    )
    return app, repo, clock


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ── Cadence is stored on the pact ─────────────────────────────────────────────


def test_create_structured_stores_cadence():
    pact = create_pact_structured(
        goal_title="Run", goal_template=None, days_per_week=5, weeks=4,
        stake_amount_cents=20000, charity_id=_CHARITY, agent="Hermes",
        consent_acknowledged=True, owner="u@e.com", clock=_clock(), settings=Settings(),
    )
    assert pact.days_per_week == 5
    assert pact.weeks == 4
    assert pact.target_count == 20


@pytest.mark.anyio
async def test_api_pact_exposes_cadence_block(tmp_path):
    app, repo, clock = _build(tmp_path)
    async with _client(app) as client:
        r = await client.post("/api/pacts/create", json={
            "goal_title": "Run", "days_per_week": 5, "weeks": 4,
            "stake_amount_cents": 20000, "charity_id": _CHARITY,
            "agent": "Hermes", "consent_acknowledged": True, "owner": "u@e.com",
        })
        assert r.status_code == 200, r.text
        pact_id = r.json()["id"]
        # The cadence block rides on the GET read-model (_with_progress).
        got = (await client.get(f"/api/pacts/{pact_id}")).json()
        cad = got["cadence"]
        assert cad["days_per_week"] == 5
        assert cad["weeks"] == 4
        assert cad["week_number"] == 1  # just created
        assert cad["this_week_target"] == 5
        assert got["progress"]["target"] == 20


# ── compute_cadence derivation ────────────────────────────────────────────────


def _pact(days_per_week=None, weeks=None, target=10, created=None, deadline=None) -> Pact:
    created = created or _NOW - timedelta(days=3)
    deadline = deadline or _NOW + timedelta(days=11)  # ~2 week span
    return Pact(
        id="pact_c", owner="a@b.com", original_prompt="x", title="t", goal="g",
        timezone="America/Los_Angeles", created_at=created, started_at=created,
        deadline_at=deadline, target_count=target, distinct_days=True,
        days_per_week=days_per_week, weeks=weeks,
        recommended_stake_cents=2000, stake_amount_cents=2000,
        charity_id=_CHARITY, charity_url="https://againstmalaria.com/donate",
        rubric=Rubric(modality=Modality.photo, must_show=["x"], min_distinct_days=5, count_target=target),
        status=PactStatus.active, stake_state=StakeState.committed,
    )


def test_derive_cadence_prefers_stored_values():
    assert derive_cadence(_pact(days_per_week=5, weeks=4, target=20)) == (5, 4)


def test_derive_cadence_reconstructs_when_missing():
    # 14-day span -> 2 weeks; target 10 / 2 weeks -> 5 days/week.
    p = _pact(days_per_week=None, weeks=None, target=10,
              created=_NOW, deadline=_NOW + timedelta(days=14))
    assert derive_cadence(p) == (5, 2)


def test_compute_cadence_counts_this_week_only():
    created = _NOW - timedelta(days=2)  # we are in week 1
    p = _pact(days_per_week=5, weeks=2, target=10, created=created,
              deadline=_NOW + timedelta(days=12))
    # 2 distinct-day passes this week + 1 pass from "last week" (before window).
    def proof(idx, when, status=ProofStatus.passed):
        return Proof(id=f"p{idx}", pact_id="pact_c", modality=Modality.photo,
                     received_at=when, day_bucket=day_bucket(when, p.timezone),
                     token_ok=True, status=status)
    proofs = [
        proof(0, created + timedelta(hours=2)),
        proof(1, created + timedelta(days=1, hours=2)),
        proof(2, created - timedelta(days=3)),  # outside this-week window
    ]
    cad = compute_cadence(p, proofs, _NOW)
    assert cad["week_number"] == 1
    assert cad["this_week_valid"] == 2
    assert cad["this_week_target"] == 5


# ── Two-phase Link donation flow ──────────────────────────────────────────────


def _donation_pending_pact(pact_id="pact-due") -> Pact:
    return _showcase_pact(
        pact_id, "Wake at 6am", PactStatus.donation_pending, dpw=5, weeks=1,
        stake=20000, charity_id=_CHARITY, created=_NOW - timedelta(days=8),
        deadline=_NOW - timedelta(days=2), verdict_at=_NOW - timedelta(days=1),
        dispute_window_closes_at=_NOW - timedelta(days=1),
    )


@pytest.mark.anyio
async def test_donation_flow_initiate_then_approve_donates_once(tmp_path):
    app, repo, clock = _build(tmp_path)
    repo.save_pact(_donation_pending_pact())
    async with _client(app) as client:
        # idle before initiate
        s = (await client.get("/api/pacts/pact-due/donation/status")).json()
        assert s["state"] == "idle"

        # initiate -> awaiting approval, no money moved yet
        r = await client.post("/api/pacts/pact-due/donation/initiate")
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "awaiting_approval"
        mid = repo.get_pact("pact-due")
        assert mid.stake_state == StakeState.executing
        assert mid.spend_request_id is None  # not captured yet

        # poll reflects awaiting
        assert (await client.get("/api/pacts/pact-due/donation/status")).json()["state"] == "awaiting_approval"

        # approve -> donated, captured once
        a = await client.post("/api/pacts/pact-due/donation/approve")
        assert a.status_code == 200, a.text
        assert a.json()["state"] == "donated"
        done = repo.get_pact("pact-due")
        assert done.status == PactStatus.donated
        assert done.stake_state == StakeState.executed
        ref = done.spend_request_id
        assert ref is not None

        # second approve is a no-op (single-fire money invariant)
        a2 = await client.post("/api/pacts/pact-due/donation/approve")
        assert a2.json()["state"] == "donated"
        assert repo.get_pact("pact-due").spend_request_id == ref


@pytest.mark.anyio
async def test_donation_initiate_rejects_non_pending(tmp_path):
    app, repo, clock = _build(tmp_path)
    p = _donation_pending_pact("pact-active")
    p.status = PactStatus.active
    repo.save_pact(p)
    async with _client(app) as client:
        r = await client.post("/api/pacts/pact-active/donation/initiate")
        assert r.status_code == 409, r.text


@pytest.mark.anyio
async def test_donation_decline_path(tmp_path):
    app, repo, clock = _build(tmp_path)
    repo.save_pact(_donation_pending_pact("pact-dec"))
    async with _client(app) as client:
        r = await client.post("/api/pacts/pact-dec/decline")
        assert r.status_code == 200, r.text
        assert repo.get_pact("pact-dec").status == PactStatus.donation_declined
        assert (await client.get("/api/pacts/pact-dec/donation/status")).json()["state"] == "declined"


# ── seed_states showcase ──────────────────────────────────────────────────────


def test_seed_states_builds_every_detail_state(repo):
    clock = FixedClock(datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc))
    settings = load_settings({})
    seed(repo, clock, settings)
    states = seed_states(repo, clock, settings)

    # State map deep-links exist and resolve to pacts in the right status.
    assert repo.get_pact(states["review"]).status == PactStatus.needs_review
    assert repo.get_pact(states["donation"]).status == PactStatus.donation_pending
    assert repo.get_pact(states["failed"]).status == PactStatus.failed
    assert repo.get_pact(states["active"]).status == PactStatus.active

    # The failed showcase has an OPEN dispute window; the donation one is closed.
    assert repo.get_pact(states["failed"]).dispute_window_closes_at > clock.now()
    assert repo.get_pact(states["donation"]).dispute_window_closes_at < clock.now()

    # Owner profile is populated so the Home stats read true.
    prof = repo.get_profile(_owner())
    assert prof is not None and prof.kept > 0

    # Every showcase pact carries explicit cadence.
    for p in repo.list_pacts(_owner()):
        if p.id.startswith("pact-") and p.id not in {"pact-win", "pact-fail", "pact-live"}:
            assert p.days_per_week and p.weeks


def _owner() -> str:
    return "colehaddad40@gmail.com"

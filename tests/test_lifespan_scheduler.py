import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from pact.charities import CHARITIES
from pact.clock import FixedClock, RealClock
from pact.config import Settings
from pact.models import (
    Modality,
    Pact,
    PactStatus,
    Rubric,
    StakeState,
)
from pact.payment import TestLinkProvider
from pact.repository import Repository


def _repo() -> Repository:
    repo = Repository.connect(":memory:")
    repo.init_schema()
    return repo


def _rubric() -> Rubric:
    return Rubric(
        modality=Modality.photo,
        must_show=["person mid-exercise"],
        min_distinct_days=2,
        count_target=2,
    )


def _active_pact(pact_id: str, created_at: datetime, deadline_at: datetime) -> Pact:
    charity = CHARITIES[0]
    return Pact(
        id=pact_id,
        owner="colehaddad40@gmail.com",
        original_prompt="work out 2x or $5 to charity",
        title="Work out 2x",
        goal="Complete 2 workout sessions on 2 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=deadline_at,
        target_count=2,
        distinct_days=True,
        recommended_stake_cents=500,
        stake_amount_cents=500,
        charity_id=charity["id"],
        charity_url=charity["donation_url"],
        freezes_allowed=1,
        rubric=_rubric(),
        status=PactStatus.active,
        stake_state=StakeState.committed,
        created_at=created_at,
        started_at=created_at,
    )


# ── 1. The ticker loop helper runs exactly one tick deterministically and stops. ──
async def test_run_ticker_loop_runs_one_tick_then_stops():
    from pact.scheduler import run_ticker_loop

    start = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(start)
    repo = _repo()
    settings = Settings()
    payment = TestLinkProvider()

    # A ghosted due active pact: one tick must settle it to failed (window opens).
    repo.save_pact(_active_pact("pact_tick", start, start - timedelta(hours=1)))

    stop = asyncio.Event()

    async def fake_sleep(seconds: float) -> None:
        # After the first tick, request shutdown so the loop exits on its next guard
        # check. No real delay — purely deterministic.
        assert seconds == settings.scheduler_interval_seconds
        stop.set()

    count = await run_ticker_loop(
        repo, clock, payment, settings, stop=stop, sleep=fake_sleep
    )

    assert count == 1  # exactly one tick ran before stop fired
    settled = repo.get_pact("pact_tick")
    assert settled.status == PactStatus.failed
    assert settled.spend_request_id is None
    assert settled.dispute_window_closes_at is not None


# ── 2. The loop exits immediately if stop is already set (zero ticks). ──
async def test_run_ticker_loop_pre_set_stop_runs_no_ticks():
    from pact.scheduler import run_ticker_loop

    start = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(start)
    repo = _repo()
    settings = Settings()
    payment = TestLinkProvider()
    repo.save_pact(_active_pact("pact_x", start, start - timedelta(hours=1)))

    stop = asyncio.Event()
    stop.set()

    async def fake_sleep(seconds: float) -> None:  # pragma: no cover - must not run
        raise AssertionError("sleep must not be called when stop is pre-set")

    count = await run_ticker_loop(
        repo, clock, payment, settings, stop=stop, sleep=fake_sleep
    )
    assert count == 0
    # Untouched: no tick ran.
    assert repo.get_pact("pact_x").status == PactStatus.active


# ── 3. Startup reconciliation settles a ghosted due pact on boot (via the lifespan). ──
async def test_lifespan_reconciles_ghosted_pact_on_startup():
    from pact.main import build_app

    start = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        # Seed a ghosted due active pact BEFORE boot, on a demo FixedClock pinned
        # past the deadline so startup reconciliation has work to do but no
        # real-time ticker spins up (demo mode).
        seed_repo = Repository.connect(path)
        seed_repo.init_schema()
        seed_repo.save_pact(
            _active_pact("pact_boot", start, start - timedelta(hours=1))
        )

        env = {
            "PACT_DB_PATH": path,
            "PACT_CLOCK_MODE": "demo",
            "PACT_DEMO_SEED_ISO": start.isoformat(),
        }
        app = build_app(env=env)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            # Entering the lifespan context triggers the lifespan startup.
            async with app.router.lifespan_context(app):
                resp = await client.get("/api/pacts/pact_boot")
                assert resp.status_code == 200
                # Startup reconciliation ran: the ghosted pact is now failed.
                assert resp.json()["status"] == PactStatus.failed.value
                assert resp.json()["spend_request_id"] is None
                assert resp.json()["dispute_window_closes_at"] is not None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ── 4. Demo mode (FixedClock) starts NO real-time ticker. ──
async def test_demo_mode_starts_no_ticker():
    from pact.main import build_app

    start = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        env = {
            "PACT_DB_PATH": path,
            "PACT_CLOCK_MODE": "demo",
            "PACT_DEMO_SEED_ISO": start.isoformat(),
        }
        app = build_app(env=env)
        async with app.router.lifespan_context(app):
            # The lifespan records its ticker task on app.state for inspection.
            assert getattr(app.state, "ticker_task", None) is None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ── 5. Real-clock mode with scheduler_enabled starts a ticker task; shutdown cancels it. ──
async def test_real_clock_starts_and_cancels_ticker():
    from pact.main import build_app

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        env = {
            "PACT_DB_PATH": path,
            "PACT_CLOCK_MODE": "real",
            # Large interval so the background ticker sleeps after its first tick
            # and never fires a second one during the test.
            "PACT_SCHEDULER_INTERVAL_SECONDS": "3600",
        }
        app = build_app(env=env)
        async with app.router.lifespan_context(app):
            task = getattr(app.state, "ticker_task", None)
            assert task is not None
            assert not task.done()
        # Lifespan shutdown must cancel the background ticker.
        assert app.state.ticker_task.done()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

from datetime import datetime, timezone

import pytest

from pact.clock import FixedClock, RealClock
from pact.config import load_settings
from pact.demo import advance_day, reset, seed
from pact.models import PactStatus, StakeState
from pact.payment import TestLinkProvider
from pact.repository import Repository


def _settings():
    # Seed instant well before the seeded pacts' deadlines so advances cross deterministically.
    return load_settings({"PACT_DEMO_SEED_ISO": "2026-06-22T09:00:00+00:00"})


def _seed_instant(settings):
    return datetime.fromisoformat(settings.demo_seed_iso)


def _repo() -> Repository:
    repo = Repository.connect(":memory:")
    repo.init_schema()
    return repo


def test_advance_day_settles_live_pact_to_failed_donation():
    settings = _settings()
    clock = FixedClock(_seed_instant(settings))
    repo = _repo()
    payment = TestLinkProvider()

    ids = seed(repo, clock, settings)
    live_id = ids["live"]

    # LIVE starts active and in-progress (2 valid proofs, target not yet met).
    live = repo.get_pact(live_id)
    assert live.status == PactStatus.active

    # Advance well past the LIVE deadline (~4 days out) with no further proofs.
    out = None
    for _ in range(6):  # 6 * 24h = 6 days > 4-day deadline
        out = advance_day(repo, clock, payment, hours=24)

    # advance_day reports the current instant and the ids it settled this call.
    assert out["now"] == clock.now().isoformat()

    settled = repo.get_pact(live_id)
    assert settled.status == PactStatus.donated
    assert settled.stake_state == StakeState.executed
    assert settled.spend_request_id == f"test_sr_{live_id}_{settled.stake_amount_cents}"

    verdict = repo.get_verdict(live_id)
    assert verdict is not None
    assert verdict.status == PactStatus.failed
    assert verdict.valid_proof_count < verdict.target_count

    # The id appears in some advance_day call's settled list across the sweeps.
    # (We re-run once more: nothing new should settle now that LIVE is terminal.)
    after = advance_day(repo, clock, payment, hours=24)
    assert live_id not in after["settled"]


def test_advance_day_settled_list_contains_crossed_pact():
    settings = _settings()
    clock = FixedClock(_seed_instant(settings))
    repo = _repo()
    payment = TestLinkProvider()

    ids = seed(repo, clock, payment_or_settings=settings) if False else seed(repo, clock, settings)
    live_id = ids["live"]

    seen_live = False
    for _ in range(6):
        out = advance_day(repo, clock, payment, hours=24)
        if live_id in out["settled"]:
            seen_live = True
    assert seen_live, "LIVE pact should appear in some advance_day settled list once its deadline passes"


def test_reset_restores_seeded_pacts_and_clock_instant():
    settings = _settings()
    clock = FixedClock(_seed_instant(settings))
    repo = _repo()
    payment = TestLinkProvider()

    seed(repo, clock, settings)

    # Mutate state: advance the clock and settle the LIVE pact away from its seeded form.
    for _ in range(6):
        advance_day(repo, clock, payment, hours=24)
    assert clock.now() != _seed_instant(settings)

    ids = reset(repo, clock, settings)

    # Clock is rewound exactly to the seed instant.
    assert clock.now() == _seed_instant(settings)

    # All three pacts exist again with the seeded ids and the seeded LIVE state.
    assert set(ids.keys()) == {"win", "fail", "live"}
    for key in ("win", "fail", "live"):
        assert repo.get_pact(ids[key]) is not None
    assert repo.get_pact(ids["live"]).status == PactStatus.active

    # reset is repeatable: stable ids across reseeds.
    ids_again = reset(repo, clock, settings)
    assert ids_again == ids
    # No leftover rows from the prior generation.
    assert {p.id for p in repo.list_pacts()} == set(ids.values())


def test_advance_day_with_real_clock_refuses():
    settings = _settings()
    repo = _repo()
    payment = TestLinkProvider()

    # Seed needs a clock; seed with a fixed clock, then attempt to advance a RealClock.
    seed(repo, FixedClock(_seed_instant(settings)), settings)

    with pytest.raises(ValueError):
        advance_day(repo, RealClock(), payment, hours=24)

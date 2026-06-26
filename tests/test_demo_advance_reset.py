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


def test_advance_day_settles_live_pact_to_failed_then_donates_after_grace():
    settings = _settings()
    clock = FixedClock(_seed_instant(settings))
    repo = _repo()
    payment = TestLinkProvider()

    ids = seed(repo, clock, settings)
    live_id = ids["live"]

    # LIVE starts active and in-progress (2 valid proofs, target not yet met).
    live = repo.get_pact(live_id)
    assert live.status == PactStatus.active

    # Advance to just past the LIVE deadline (~4 days out) but only by 12h
    # so we land after the deadline but before the 24h grace window closes.
    # The seed instant is 09:00 UTC; the deadline is seed_instant + 4 days.
    # Advance 4 days + 12h puts us 12h past the deadline but 12h before grace.
    for _ in range(4):
        advance_day(repo, clock, payment, settings, hours=24)
    advance_day(repo, clock, payment, settings, hours=12)

    # Deferred-donation contract: deadline crossed -> failed + open dispute window,
    # but NO money moved yet (grace window still open).
    failed = repo.get_pact(live_id)
    assert failed.status == PactStatus.failed
    assert failed.dispute_window_closes_at is not None
    assert failed.spend_request_id is None
    assert failed.stake_state == StakeState.committed

    verdict = repo.get_verdict(live_id)
    assert verdict is not None
    assert verdict.status == PactStatus.failed
    assert verdict.valid_proof_count < verdict.target_count
    assert verdict.payment_action == "none"

    # Now advance past the grace window so the dispute window closes -> donation executes.
    advance_day(repo, clock, payment, settings, hours=24)

    donated = repo.get_pact(live_id)
    assert donated.status == PactStatus.donated
    assert donated.stake_state == StakeState.executed
    assert donated.spend_request_id == f"test_sr_{live_id}_{donated.stake_amount_cents}"

    final_verdict = repo.get_verdict(live_id)
    assert final_verdict.payment_action == "donation_executed"
    assert final_verdict.payment_ref == f"test_sr_{live_id}_{donated.stake_amount_cents}"

    # Idempotent: nothing new settles or donates once LIVE is terminal.
    after = advance_day(repo, clock, payment, settings, hours=24)
    assert live_id not in after["settled"]
    assert live_id not in after["donated"]
    assert repo.get_pact(live_id).spend_request_id == f"test_sr_{live_id}_{donated.stake_amount_cents}"


def test_advance_day_settled_and_donated_lists_report_the_crossed_pact():
    settings = _settings()
    clock = FixedClock(_seed_instant(settings))
    repo = _repo()
    payment = TestLinkProvider()

    ids = seed(repo, clock, settings)
    live_id = ids["live"]

    seen_settled = False
    seen_donated = False
    for _ in range(8):  # cross the deadline AND the grace window over the sweeps
        out = advance_day(repo, clock, payment, settings, hours=24)
        if live_id in out["settled"]:
            seen_settled = True
        if live_id in out["donated"]:
            seen_donated = True
    assert seen_settled, "LIVE pact should appear in some advance_day 'settled' list once its deadline passes"
    assert seen_donated, "LIVE pact should appear in some advance_day 'donated' list once its grace window closes"


def test_reset_restores_seeded_pacts_and_clock_instant():
    settings = _settings()
    clock = FixedClock(_seed_instant(settings))
    repo = _repo()
    payment = TestLinkProvider()

    seed(repo, clock, settings)

    # Mutate state: advance the clock and settle the LIVE pact away from its seeded form.
    for _ in range(8):
        advance_day(repo, clock, payment, settings, hours=24)
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
        advance_day(repo, RealClock(), payment, settings, hours=24)

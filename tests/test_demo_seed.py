from datetime import datetime, timezone

from pact.clock import FixedClock
from pact.config import load_settings
from pact.demo import seed
from pact.models import PactStatus, ProofStatus, StakeState


def _clock() -> FixedClock:
    # Pinned demo instant; deadlines are seeded relative to this.
    return FixedClock(datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc))


def test_seed_returns_three_stable_ids(repo):
    clock = _clock()
    settings = load_settings({})

    ids = seed(repo, clock, settings)

    assert set(ids.keys()) == {"win", "fail", "live"}
    assert ids["win"].startswith("pact-win")
    assert ids["fail"].startswith("pact-fail")
    assert ids["live"].startswith("pact-live")
    assert len({ids["win"], ids["fail"], ids["live"]}) == 3

    # Exactly three pacts persisted.
    assert len(repo.list_pacts()) == 3
    for key in ("win", "fail", "live"):
        assert repo.get_pact(ids[key]) is not None


def test_seed_ids_are_stable_across_runs(repo):
    settings = load_settings({})
    ids_a = seed(repo, _clock(), settings)
    ids_b = seed(repo, _clock(), settings)
    assert ids_a == ids_b
    # Re-seeding overwrites in place; still exactly three pacts.
    assert len(repo.list_pacts()) == 3


def test_win_is_succeeded_with_five_valid_proofs_and_no_spend(repo):
    clock = _clock()
    settings = load_settings({})
    ids = seed(repo, clock, settings)

    win = repo.get_pact(ids["win"])
    assert win.status == PactStatus.succeeded
    assert win.stake_state == StakeState.released
    assert win.spend_request_id is None  # provably zero link-cli on success

    proofs = repo.list_proofs(win.id)
    passed = [p for p in proofs if p.status == ProofStatus.passed]
    assert len(passed) == 5
    # 5 distinct calendar days.
    assert len({p.day_bucket for p in passed}) == 5
    assert win.target_count == 5

    verdict = repo.get_verdict(win.id)
    assert verdict is not None
    assert verdict.status == PactStatus.succeeded
    assert verdict.valid_proof_count == 5


def test_fail_is_donated_with_spend_request_id(repo):
    clock = _clock()
    settings = load_settings({})
    ids = seed(repo, clock, settings)

    fail = repo.get_pact(ids["fail"])
    assert fail.status in {PactStatus.donated, PactStatus.failed}
    assert fail.spend_request_id is not None  # donation fired on shortfall
    # Deadline is in the past relative to the demo clock.
    assert fail.deadline_at <= clock.now()

    proofs = repo.list_proofs(fail.id)
    passed = [p for p in proofs if p.status == ProofStatus.passed]
    assert len(passed) == 4
    assert len({p.day_bucket for p in passed}) == 4
    assert fail.target_count == 5

    verdict = repo.get_verdict(fail.id)
    assert verdict is not None
    assert verdict.status == PactStatus.failed


def test_live_is_active_with_two_proofs_and_future_deadline(repo):
    clock = _clock()
    settings = load_settings({})
    ids = seed(repo, clock, settings)

    live = repo.get_pact(ids["live"])
    assert live.status == PactStatus.active
    assert live.spend_request_id is None
    assert live.deadline_at > clock.now()  # in progress

    proofs = repo.list_proofs(live.id)
    passed = [p for p in proofs if p.status == ProofStatus.passed]
    assert len(passed) == 2
    assert len({p.day_bucket for p in passed}) == 2
    assert live.target_count == 5

    # LIVE has not been settled yet.
    assert repo.get_verdict(live.id) is None


def test_seed_stays_within_stake_caps(repo):
    settings = load_settings({})
    ids = seed(repo, _clock(), settings)
    for key in ("win", "fail", "live"):
        pact = repo.get_pact(ids[key])
        assert settings.min_stake_cents <= pact.stake_amount_cents <= settings.max_stake_cents
        assert pact.charity_id == "against_malaria_foundation"

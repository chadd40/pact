from datetime import datetime, timezone

from pact.anticheat import TokenStore
from pact.clock import FixedClock


def _clock() -> FixedClock:
    return FixedClock(datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc))


def test_issued_token_verifies_exactly_once():
    clock = _clock()
    store = TokenStore(ttl_minutes=10)
    token = store.issue("pact_a1b2c3", clock)

    assert isinstance(token, str)
    assert token != ""
    # First verify succeeds.
    assert store.verify("pact_a1b2c3", token, clock) is True
    # Second verify fails because the token is single-use (now marked used).
    assert store.verify("pact_a1b2c3", token, clock) is False


def test_expired_token_fails_after_ttl():
    clock = _clock()
    store = TokenStore(ttl_minutes=10)
    token = store.issue("pact_a1b2c3", clock)

    # Move the clock past the 10-minute TTL.
    clock.advance(minutes=11)
    assert store.verify("pact_a1b2c3", token, clock) is False


def test_token_within_ttl_still_verifies():
    clock = _clock()
    store = TokenStore(ttl_minutes=10)
    token = store.issue("pact_a1b2c3", clock)

    # Just inside the TTL window.
    clock.advance(minutes=9)
    assert store.verify("pact_a1b2c3", token, clock) is True


def test_wrong_pact_id_fails():
    clock = _clock()
    store = TokenStore(ttl_minutes=10)
    token = store.issue("pact_a1b2c3", clock)

    # Same token, different pact -> reject; original pact still valid.
    assert store.verify("pact_other", token, clock) is False
    assert store.verify("pact_a1b2c3", token, clock) is True


def test_unknown_token_fails():
    clock = _clock()
    store = TokenStore(ttl_minutes=10)
    assert store.verify("pact_a1b2c3", "PACT-ZZ", clock) is False

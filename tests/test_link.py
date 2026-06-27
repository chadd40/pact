from datetime import datetime, timezone

from pact.clock import FixedClock
from pact.link import connect_account, new_account


def _clock() -> FixedClock:
    return FixedClock(datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc))


def test_new_account_defaults_disconnected():
    acct = new_account("a@b.com")
    assert acct.owner == "a@b.com"
    assert acct.connected is False
    assert acct.funding_ref is None
    assert acct.connected_at is None


def test_connect_sets_connected_and_funding_ref():
    clock = _clock()
    acct = connect_account(new_account("a@b.com"), clock)
    assert acct.connected is True
    assert acct.funding_ref == "test_funding_a@b.com"
    assert acct.connected_at == clock.now()


def test_connect_is_idempotent():
    clock = _clock()
    once = connect_account(new_account("a@b.com"), clock)
    later = FixedClock(datetime(2026, 7, 1, tzinfo=timezone.utc))
    twice = connect_account(once, later)
    # Re-connecting changes nothing (keeps the original connected_at).
    assert twice.connected_at == clock.now()
    assert twice.funding_ref == "test_funding_a@b.com"


def test_repo_round_trips_link_account(tmp_path):
    from pact.repository import Repository

    repo = Repository.connect(str(tmp_path / "p.db"))
    repo.init_schema()
    assert repo.get_link_account("a@b.com") is None
    repo.save_link_account(connect_account(new_account("a@b.com"), _clock()))
    got = repo.get_link_account("a@b.com")
    assert got is not None and got.connected is True
    assert got.funding_ref == "test_funding_a@b.com"

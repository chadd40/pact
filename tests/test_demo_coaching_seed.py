from datetime import datetime, timezone

from pact.clock import FixedClock
from pact.config import load_settings
from pact.demo import reset, seed


def _clock() -> FixedClock:
    # Same pinned demo instant the other demo tests use.
    return FixedClock(datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc))


_OWNER = "colehaddad40@gmail.com"


def test_seed_creates_outbound_coaching_on_live(repo):
    clock = _clock()
    settings = load_settings({})

    ids = seed(repo, clock, settings)
    live_id = ids["live"]

    msgs = repo.list_coaching_messages(live_id)
    outbound = [m for m in msgs if m.direction == "outbound"]
    assert len(outbound) >= 1
    # All seeded coaching rows hang off the LIVE pact only.
    assert all(m.pact_id == live_id for m in outbound)
    # They carry real, recognized triggers and non-empty bodies.
    triggers = {m.trigger for m in outbound}
    assert triggers.issubset({"mid_week", "behind_pace"})
    assert "mid_week" in triggers
    for m in outbound:
        assert m.channel == "web"
        assert m.body.strip()
        assert m.delivered_at is None  # undelivered -> shows up in outbox


def test_seeded_coaching_is_visible_in_outbox(repo):
    clock = _clock()
    settings = load_settings({})

    seed(repo, clock, settings)

    out = repo.outbox(_OWNER)
    assert len(out) >= 1
    assert all(m.direction == "outbound" for m in out)
    assert all(m.delivered_at is None for m in out)


def test_coaching_ids_are_stable_across_seed(repo):
    settings = load_settings({})

    ids_a = seed(repo, _clock(), settings)
    msgs_a = repo.list_coaching_messages(ids_a["live"])
    ids_b = seed(repo, _clock(), settings)
    msgs_b = repo.list_coaching_messages(ids_b["live"])

    # Re-seeding overwrites in place (stable ids): no duplication.
    assert {m.id for m in msgs_a} == {m.id for m in msgs_b}
    assert len(msgs_a) == len(msgs_b)


def test_reset_clears_and_reseeds_coaching(repo):
    settings = load_settings({})

    seed(repo, _clock(), settings)
    ids = reset(repo, _clock(), settings)

    msgs = repo.list_coaching_messages(ids["live"])
    outbound = [m for m in msgs if m.direction == "outbound"]
    # Reset wiped coaching_messages then reseeded -> still exactly the seeded set.
    assert len(outbound) >= 1
    out = repo.outbox("colehaddad40@gmail.com")
    assert len(out) == len(outbound)

"""T3/T4/T5: failure dispute message, celebrate+renew nudge, 5pm timezone gate."""
from datetime import datetime, timedelta, timezone

from pact.clock import FixedClock
from pact.coaching import failed_dispute_message, renew_message, should_nudge
from pact.config import Settings
from pact.models import Modality, Pact, PactStatus, Rubric, StakeState
from pact.payment import TestLinkProvider
from pact.repository import Repository
from pact.scheduler import tick


def _clock(h=18):
    return FixedClock(datetime(2026, 6, 24, h, 0, 0, tzinfo=timezone.utc))


def _pact(status, **kw):
    base = dict(
        id="pact_m", owner="demo@pact.local", original_prompt="x", title="Work out 5x", goal="g",
        timezone="America/Los_Angeles", deadline_at=datetime(2026, 6, 28, 23, 59, 59, tzinfo=timezone.utc),
        target_count=5, recommended_stake_cents=2000, stake_amount_cents=2000,
        charity_id="against_malaria_foundation", charity_url="https://againstmalaria.com/donate",
        rubric=Rubric(modality=Modality.photo, must_show=["x"], min_distinct_days=5, count_target=5),
        status=status, stake_state=StakeState.committed, created_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
    )
    base.update(kw)
    return Pact(**base)


def _repo(tmp_path):
    r = Repository.connect(str(tmp_path / "p.db"))
    r.init_schema()
    return r


# ---- T3: failure dispute message --------------------------------------------

def test_failed_dispute_message_states_the_window():
    c = _clock()
    p = _pact(PactStatus.failed, dispute_window_closes_at=c.now() + timedelta(hours=24))
    m = failed_dispute_message(p, c)
    assert m.trigger == "failed" and m.direction == "outbound"
    assert "dispute" in m.body.lower()


def test_tick_emits_failed_dispute_message_once(tmp_path):
    r, c = _repo(tmp_path), _clock()
    r.save_pact(_pact(PactStatus.failed, dispute_window_closes_at=c.now() + timedelta(hours=24)))
    tick(r, c, TestLinkProvider(), Settings())
    failed = [m for m in r.list_coaching_messages("pact_m") if m.trigger == "failed"]
    assert len(failed) == 1
    tick(r, c, TestLinkProvider(), Settings())  # idempotent
    assert len([m for m in r.list_coaching_messages("pact_m") if m.trigger == "failed"]) == 1


# ---- T4: celebrate + renew --------------------------------------------------

def test_renew_message_success_and_paid():
    c = _clock()
    s = renew_message(_pact(PactStatus.succeeded), c)
    assert s.trigger == "renew" and s.direction == "outbound"
    d = renew_message(_pact(PactStatus.donation_complete), c)
    assert d.trigger == "renew"


def test_tick_emits_renew_once_on_succeeded(tmp_path):
    r, c = _repo(tmp_path), _clock()
    r.save_pact(_pact(PactStatus.succeeded))
    tick(r, c, TestLinkProvider(), Settings())
    assert len([m for m in r.list_coaching_messages("pact_m") if m.trigger == "renew"]) == 1
    tick(r, c, TestLinkProvider(), Settings())
    assert len([m for m in r.list_coaching_messages("pact_m") if m.trigger == "renew"]) == 1


def test_tick_emits_renew_on_donation_complete(tmp_path):
    r, c = _repo(tmp_path), _clock()
    r.save_pact(_pact(PactStatus.donation_complete))
    tick(r, c, TestLinkProvider(), Settings())
    assert len([m for m in r.list_coaching_messages("pact_m") if m.trigger == "renew"]) == 1


# ---- T5: 5pm timezone-aware gate --------------------------------------------

def test_should_nudge_respects_nudge_hour_local():
    # America/Los_Angeles (PDT=UTC-7). 18:00 UTC = 11:00 local -> before 17 -> suppressed.
    p = _pact(PactStatus.active, deadline_at=datetime(2026, 6, 30, tzinfo=timezone.utc))
    assert should_nudge(p, [], [], _clock(18), nudge_hour=17) is None
    # 2026-06-25 01:00 UTC = 2026-06-24 18:00 local -> at/after 17 -> fires.
    after = FixedClock(datetime(2026, 6, 25, 1, 0, 0, tzinfo=timezone.utc))
    assert should_nudge(p, [], [], after, nudge_hour=17) is not None
    # Default (no nudge_hour) keeps the old behavior (no time gate).
    assert should_nudge(p, [], [], _clock(18)) is not None

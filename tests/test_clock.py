from datetime import datetime, timedelta, timezone

from pact.clock import Clock, RealClock, FixedClock


def test_fixed_clock_now_is_stable():
    base = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(base)
    first = clock.now()
    second = clock.now()
    assert first == base
    assert second == base
    assert first == second


def test_fixed_clock_set_replaces_instant():
    base = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(base)
    new = datetime(2026, 7, 1, 9, 30, 0, tzinfo=timezone.utc)
    clock.set(new)
    assert clock.now() == new


def test_fixed_clock_advance_hours():
    base = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(base)
    clock.advance(hours=24)
    assert clock.now() == base + timedelta(hours=24)


def test_fixed_clock_advance_days_and_minutes():
    base = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(base)
    clock.advance(days=2, minutes=30)
    assert clock.now() == base + timedelta(days=2, minutes=30)


def test_fixed_clock_advance_is_cumulative():
    base = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(base)
    clock.advance(hours=1)
    clock.advance(hours=2)
    assert clock.now() == base + timedelta(hours=3)


def test_fixed_clock_advance_fractional_hours():
    base = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(base)
    clock.advance(hours=1.5)
    assert clock.now() == base + timedelta(hours=1.5)


def test_real_clock_returns_tz_aware_utc():
    clock = RealClock()
    now = clock.now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_clocks_satisfy_protocol():
    fixed: Clock = FixedClock(datetime(2026, 6, 24, tzinfo=timezone.utc))
    real: Clock = RealClock()
    assert isinstance(fixed.now(), datetime)
    assert isinstance(real.now(), datetime)

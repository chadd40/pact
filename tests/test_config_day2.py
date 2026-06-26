from datetime import datetime, timezone

from pact.config import Settings, load_settings


def test_new_fields_default_to_real_clock_mode():
    s = load_settings({})
    assert s.clock_mode == "real"
    assert s.demo_seed_iso == "2026-06-22T09:00:00+00:00"


def test_default_constructor_has_new_fields():
    s = Settings()
    assert s.clock_mode == "real"
    assert s.demo_seed_iso == "2026-06-22T09:00:00+00:00"


def test_none_env_uses_new_defaults():
    assert load_settings(None) == Settings()


def test_clock_mode_env_override_to_demo():
    s = load_settings({"PACT_CLOCK_MODE": "demo"})
    assert s.clock_mode == "demo"
    # Day-1 fields remain untouched by the new env key.
    assert s.reasoning_mode == "hybrid"
    assert s.demo_seed_iso == "2026-06-22T09:00:00+00:00"


def test_demo_seed_iso_env_override():
    s = load_settings({"PACT_DEMO_SEED_ISO": "2030-01-01T00:00:00+00:00"})
    assert s.demo_seed_iso == "2030-01-01T00:00:00+00:00"
    assert s.clock_mode == "real"


def test_default_demo_seed_iso_parses_tz_aware():
    s = Settings()
    parsed = datetime.fromisoformat(s.demo_seed_iso)
    assert parsed.tzinfo is not None
    assert parsed == datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)


def test_overridden_demo_seed_iso_parses_tz_aware():
    s = load_settings({"PACT_DEMO_SEED_ISO": "2030-01-01T00:00:00+00:00"})
    parsed = datetime.fromisoformat(s.demo_seed_iso)
    assert parsed.tzinfo is not None
    assert parsed == datetime(2030, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

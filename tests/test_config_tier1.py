import pytest

from pact.config import Settings, load_settings


def test_tier1_defaults_match_contract():
    s = load_settings({})
    assert s.reasoning_timeout_polls == 0
    assert s.scheduler_enabled is True
    assert s.scheduler_interval_seconds == 60


def test_tier1_default_constructor_matches():
    s = Settings()
    assert s.reasoning_timeout_polls == 0
    assert s.scheduler_enabled is True
    assert s.scheduler_interval_seconds == 60


def test_none_env_uses_tier1_defaults():
    assert load_settings(None) == Settings()


def test_reasoning_timeout_polls_env_override():
    s = load_settings({"PACT_REASONING_TIMEOUT_POLLS": "5"})
    assert s.reasoning_timeout_polls == 5
    # untouched keys keep contract defaults
    assert s.scheduler_enabled is True
    assert s.scheduler_interval_seconds == 60
    assert s.reasoning_mode == "hybrid"


def test_scheduler_interval_seconds_env_override():
    s = load_settings({"PACT_SCHEDULER_INTERVAL_SECONDS": "120"})
    assert s.scheduler_interval_seconds == 120
    assert s.reasoning_timeout_polls == 0
    assert s.scheduler_enabled is True


def test_reasoning_timeout_polls_bad_int_raises_clear_error():
    with pytest.raises(ValueError) as exc:
        load_settings({"PACT_REASONING_TIMEOUT_POLLS": "soon"})
    msg = str(exc.value)
    assert "PACT_REASONING_TIMEOUT_POLLS" in msg
    assert "soon" in msg


@pytest.mark.parametrize("raw", ["false", "False", "FALSE", "0", "no", "off", "  no  "])
def test_scheduler_enabled_parses_falsey(raw):
    s = load_settings({"PACT_SCHEDULER_ENABLED": raw})
    assert s.scheduler_enabled is False


@pytest.mark.parametrize("raw", ["true", "True", "TRUE", "1", "yes", "on", "  YES  "])
def test_scheduler_enabled_parses_truthy(raw):
    s = load_settings({"PACT_SCHEDULER_ENABLED": raw})
    assert s.scheduler_enabled is True


def test_scheduler_enabled_blank_keeps_default_true():
    # empty string is not an explicit override -> default True
    s = load_settings({"PACT_SCHEDULER_ENABLED": ""})
    assert s.scheduler_enabled is True


def test_scheduler_enabled_unknown_raises_clear_error():
    with pytest.raises(ValueError) as exc:
        load_settings({"PACT_SCHEDULER_ENABLED": "maybe"})
    msg = str(exc.value)
    assert "PACT_SCHEDULER_ENABLED" in msg
    assert "maybe" in msg


def test_settings_still_frozen_with_new_fields():
    s = load_settings({})
    with pytest.raises(Exception):
        s.scheduler_interval_seconds = 999  # type: ignore[misc]


def test_full_tier1_env_override_together():
    env = {
        "PACT_REASONING_TIMEOUT_POLLS": "3",
        "PACT_SCHEDULER_ENABLED": "false",
        "PACT_SCHEDULER_INTERVAL_SECONDS": "15",
    }
    s = load_settings(env)
    assert s.reasoning_timeout_polls == 3
    assert s.scheduler_enabled is False
    assert s.scheduler_interval_seconds == 15

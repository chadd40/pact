import pytest

from pact.config import Settings, load_settings


def test_defaults_match_contract():
    s = load_settings({})
    assert isinstance(s, Settings)
    assert s.reasoning_mode == "hybrid"
    assert s.payment_mode == "test_link"
    assert s.min_stake_cents == 500
    assert s.max_stake_cents == 2000
    assert s.default_freezes == 1
    assert s.freeze_extension_hours == 24
    assert s.dispute_grace_hours == 24
    assert s.cooling_off_minutes == 60
    assert s.db_path == "pact.db"
    assert s.artifacts_dir == "artifacts"


def test_none_env_uses_defaults():
    assert load_settings(None) == Settings()


def test_settings_default_constructor_matches():
    s = Settings()
    assert s.reasoning_mode == "hybrid"
    assert s.payment_mode == "test_link"
    assert s.min_stake_cents == 500
    assert s.max_stake_cents == 2000
    assert s.default_freezes == 1
    assert s.freeze_extension_hours == 24
    assert s.dispute_grace_hours == 24
    assert s.cooling_off_minutes == 60
    assert s.db_path == "pact.db"
    assert s.artifacts_dir == "artifacts"


def test_full_env_override():
    env = {
        "PACT_REASONING_MODE": "agent_only",
        "PACT_PAYMENT_MODE": "link_cli",
        "PACT_MIN_STAKE_CENTS": "1000",
        "PACT_MAX_STAKE_CENTS": "5000",
        "PACT_DEFAULT_FREEZES": "2",
        "PACT_FREEZE_EXTENSION_HOURS": "48",
        "PACT_DISPUTE_GRACE_HOURS": "12",
        "PACT_COOLING_OFF_MINUTES": "30",
        "PACT_DB_PATH": "/tmp/custom.db",
        "PACT_ARTIFACTS_DIR": "/tmp/art",
    }
    s = load_settings(env)
    assert s.reasoning_mode == "agent_only"
    assert s.payment_mode == "link_cli"
    assert s.min_stake_cents == 1000
    assert s.max_stake_cents == 5000
    assert s.default_freezes == 2
    assert s.freeze_extension_hours == 48
    assert s.dispute_grace_hours == 12
    assert s.cooling_off_minutes == 30
    assert s.db_path == "/tmp/custom.db"
    assert s.artifacts_dir == "/tmp/art"


def test_partial_override_keeps_defaults():
    s = load_settings({"PACT_MAX_STAKE_CENTS": "9999"})
    assert s.max_stake_cents == 9999
    # untouched keys keep contract defaults
    assert s.min_stake_cents == 500
    assert s.reasoning_mode == "hybrid"
    assert s.db_path == "pact.db"


def test_settings_is_frozen():
    s = load_settings({})
    with pytest.raises(Exception):
        s.max_stake_cents = 1234  # type: ignore[misc]


def test_bad_int_raises_clear_error():
    with pytest.raises(ValueError) as exc:
        load_settings({"PACT_MAX_STAKE_CENTS": "not-a-number"})
    msg = str(exc.value)
    assert "PACT_MAX_STAKE_CENTS" in msg
    assert "not-a-number" in msg


def test_blank_int_raises_clear_error():
    with pytest.raises(ValueError) as exc:
        load_settings({"PACT_MIN_STAKE_CENTS": ""})
    assert "PACT_MIN_STAKE_CENTS" in str(exc.value)

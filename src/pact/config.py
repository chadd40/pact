from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Settings:
    reasoning_mode: str = "hybrid"
    payment_mode: str = "test_link"
    min_stake_cents: int = 500
    max_stake_cents: int = 2000
    default_freezes: int = 1
    freeze_extension_hours: int = 24
    dispute_grace_hours: int = 24
    cooling_off_minutes: int = 60
    db_path: str = "pact.db"
    artifacts_dir: str = "artifacts"
    clock_mode: str = "real"
    demo_seed_iso: str = "2026-06-22T09:00:00+00:00"
    notification_mode: str = "test"


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{key} must be an integer, got {raw!r}") from None


def _str(env: Mapping[str, str], key: str, default: str) -> str:
    raw = env.get(key)
    return default if raw is None else raw


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = env or {}
    return Settings(
        reasoning_mode=_str(env, "PACT_REASONING_MODE", "hybrid"),
        payment_mode=_str(env, "PACT_PAYMENT_MODE", "test_link"),
        min_stake_cents=_int(env, "PACT_MIN_STAKE_CENTS", 500),
        max_stake_cents=_int(env, "PACT_MAX_STAKE_CENTS", 2000),
        default_freezes=_int(env, "PACT_DEFAULT_FREEZES", 1),
        freeze_extension_hours=_int(env, "PACT_FREEZE_EXTENSION_HOURS", 24),
        dispute_grace_hours=_int(env, "PACT_DISPUTE_GRACE_HOURS", 24),
        cooling_off_minutes=_int(env, "PACT_COOLING_OFF_MINUTES", 60),
        db_path=_str(env, "PACT_DB_PATH", "pact.db"),
        artifacts_dir=_str(env, "PACT_ARTIFACTS_DIR", "artifacts"),
        clock_mode=_str(env, "PACT_CLOCK_MODE", "real"),
        demo_seed_iso=_str(env, "PACT_DEMO_SEED_ISO", "2026-06-22T09:00:00+00:00"),
        notification_mode=_str(env, "PACT_NOTIFICATION_MODE", "test"),
    )

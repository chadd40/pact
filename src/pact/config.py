from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Settings:
    reasoning_mode: str = "hybrid"
    payment_mode: str = "test_link"
    min_stake_cents: int = 1000
    max_stake_cents: int = 50000
    default_freezes: int = 1
    freeze_extension_hours: int = 24
    dispute_grace_hours: int = 24
    cooling_off_minutes: int = 60
    db_path: str = "pact.db"
    artifacts_dir: str = "artifacts"
    clock_mode: str = "real"
    demo_seed_iso: str = "2026-06-22T09:00:00+00:00"
    link_mode: str = "dry_run"
    reasoning_timeout_polls: int = 0
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 60


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


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    norm = raw.strip().lower()
    if norm == "":
        return default
    if norm in _TRUE:
        return True
    if norm in _FALSE:
        return False
    raise ValueError(
        f"{key} must be a boolean (one of {sorted(_TRUE | _FALSE)}), got {raw!r}"
    )


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = env or {}
    return Settings(
        reasoning_mode=_str(env, "PACT_REASONING_MODE", "hybrid"),
        payment_mode=_str(env, "PACT_PAYMENT_MODE", "test_link"),
        min_stake_cents=_int(env, "PACT_MIN_STAKE_CENTS", 1000),
        max_stake_cents=_int(env, "PACT_MAX_STAKE_CENTS", 50000),
        default_freezes=_int(env, "PACT_DEFAULT_FREEZES", 1),
        freeze_extension_hours=_int(env, "PACT_FREEZE_EXTENSION_HOURS", 24),
        dispute_grace_hours=_int(env, "PACT_DISPUTE_GRACE_HOURS", 24),
        cooling_off_minutes=_int(env, "PACT_COOLING_OFF_MINUTES", 60),
        db_path=_str(env, "PACT_DB_PATH", "pact.db"),
        artifacts_dir=_str(env, "PACT_ARTIFACTS_DIR", "artifacts"),
        clock_mode=_str(env, "PACT_CLOCK_MODE", "real"),
        demo_seed_iso=_str(env, "PACT_DEMO_SEED_ISO", "2026-06-22T09:00:00+00:00"),
        link_mode=_str(env, "PACT_LINK_MODE", "dry_run"),
        reasoning_timeout_polls=_int(env, "PACT_REASONING_TIMEOUT_POLLS", 0),
        scheduler_enabled=_bool(env, "PACT_SCHEDULER_ENABLED", True),
        scheduler_interval_seconds=_int(env, "PACT_SCHEDULER_INTERVAL_SECONDS", 60),
    )

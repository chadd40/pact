# Pact Engine Spine — Implementation Plan (Day 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the runnable, fully-tested Pact backend engine — the full draft→proof→verdict→test-donation loop — with deterministic test providers, so success moves zero money and failure executes a (test) charity donation, all behind an HTTP API.

**Architecture:** A FastAPI + Pydantic + SQLite service. Reasoning (draft/judge/coach/verdict) and payment sit behind provider seams; this plan implements the deterministic `test_llm` and `test_link` providers (the real Hermes-agent broker and live Link are later plans). All time flows through an injected `Clock` so the demo clock and tests are deterministic. Anti-cheat (nonce token, server-time distinct-day bucketing, perceptual-hash dedup) runs before the agent ever judges.

**Tech Stack:** Python 3.11+, uv, FastAPI, Pydantic v2, SQLite (stdlib), pytest + httpx, Pillow + imagehash.

**Scope (this plan = engine spine only):** NOT included here — web UI, the real Hermes reasoning broker / `/pact serve`, live Link virtual-card + browser automation, coaching scheduler/email, streaks/Owner profile, and the demo seed/advance-day endpoints. Those are follow-on plans (spec §14 Day 2/3 + stretch).

**Spec:** [`docs/superpowers/specs/2026-06-24-pact-design.md`](../specs/2026-06-24-pact-design.md)

---

## Interface Contract (frozen — every task below adheres to these names/signatures)

**Conventions:** all datetimes are timezone-aware; logic never calls `datetime.now()` directly — it takes an injected `Clock`. Money is integer cents. IDs are strings.

**Modules** (`src/pact/`): `clock.py`, `config.py`, `models.py`, `repository.py`, `charities.py`, `anticheat.py`, `reasoning.py`, `payment.py`, `lifecycle.py`, `packet.py`, `api.py`, `main.py`.

**Enums** (`models.py`, all `(str, Enum)`): `PactStatus` (draft, active, evaluating, succeeded, failed, needs_review, canceled_release, canceled_forfeit, donation_pending, donated, donation_failed, donation_declined) · `StakeState` (none, committed, executing, executed, released, declined, error) · `ProofStatus` (passed, failed, ambiguous) · `Modality` (photo, log, url, file, text) · `TaskType` (draft, judge_proof, coach, verdict) · `TaskStatus` (pending, claimed, done, failed) · `PaymentAction` (none, donation_executed, donation_failed, donation_declined, cancelled).

**Models** (`models.py`): `Rubric`, `Pact`, `Proof`, `Verdict`, `ReasoningTask` (fields per task code).

**Key seams:**
- `Clock` Protocol → `RealClock`, `FixedClock(set/advance)`.
- `ReasoningProvider` Protocol (`capabilities()`, `resolve(task)`) → `TestLLMProvider` (deterministic; `capabilities()=={"text","vision"}`). **judge_proof rule:** `passed` IFF `token_ok and not is_duplicate and content_ok`; not-token → `failed`; duplicate → `failed`; not-content → `ambiguous`.
- `PaymentProvider` Protocol (`create_donation(pact, idempotency_key)`) → `TestLinkProvider` (`provider="test_link"`).
- `Repository` (SQLite, json column + indexed id/owner/status/deadline_at).
- `lifecycle.py`: `draft_pact`, `confirm_and_start`, `submit_proof`, `spend_freeze`, `cancel`, `settle`, `submit_dispute`, `reconcile_on_startup`, `transition`/`ALLOWED_TRANSITIONS`, `new_pact_id`.

**Core invariants enforced by tests:** success path makes **zero** payment calls and leaves `spend_request_id is None`; `settle` is idempotent (no double donation); a freeze extends `deadline_at`; cancel within the cooling-off window releases, after forfeits; ghosting + server restart still settles via `reconcile_on_startup`.

---

## Tasks


### Task 1: Project scaffold + tooling

**Files:**
- Create: `pyproject.toml`
- Create: `src/pact/__init__.py`
- Test: `tests/conftest.py`, `tests/test_smoke.py`

This task stands up the `uv` project, wires `pythonpath=["src"]` so `import pact` resolves, and provides two reusable pytest fixtures used by every later task: a `FixedClock` and a tmp-file SQLite `Repository`. It ends on one trivial passing smoke test. Note: `conftest.py` references `pact.clock.FixedClock` and `pact.repository.Repository` — those modules are built in Task 2 (Clock) and Task 4 (Repository). For *this* task the smoke test must NOT use those fixtures yet; it only asserts the package imports. The fixtures are placed in `conftest.py` now (per the task spec) but exercised by later tasks. To keep `conftest.py` importable before Tasks 2/4 land, the fixtures import lazily *inside* the fixture body, so collection of `test_smoke.py` never triggers the missing imports.

- [ ] **Step 1: Write the failing test**

  Create `tests/test_smoke.py`:

  ```python
  def test_package_imports():
      import pact

      assert pact.__name__ == "pact"
  ```

  Create `tests/conftest.py` (fixtures defined now, imported lazily so they don't break collection before Tasks 2 & 4 exist):

  ```python
  import os
  import tempfile
  from datetime import datetime, timezone

  import pytest


  @pytest.fixture
  def fixed_clock():
      """A FixedClock pinned to a deterministic instant (Task 2 provides FixedClock)."""
      from pact.clock import FixedClock

      return FixedClock(datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc))


  @pytest.fixture
  def repo():
      """A Repository backed by a throwaway on-disk SQLite file (Task 4 provides Repository)."""
      from pact.repository import Repository

      fd, path = tempfile.mkstemp(suffix=".db")
      os.close(fd)
      repository = Repository.connect(path)
      repository.init_schema()
      try:
          yield repository
      finally:
          try:
              os.remove(path)
          except OSError:
              pass
  ```

- [ ] **Step 2: Run it (expected FAIL)**

  ```
  uv run pytest tests/test_smoke.py::test_package_imports -v
  ```

  Expected: FAIL — collection/import error `ModuleNotFoundError: No module named 'pact'` (no `pyproject.toml` configuring `pythonpath`, and `src/pact/__init__.py` does not exist yet).

- [ ] **Step 3: Minimal implementation**

  Create `pyproject.toml`:

  ```python
  # pyproject.toml  (TOML, shown in a python block for fenced formatting)
  [project]
  name = "pact"
  version = "0.1.0"
  description = "Pact — a self-binding commitment engine."
  requires-python = ">=3.11"
  dependencies = [
      "fastapi",
      "uvicorn[standard]",
      "pydantic>=2",
      "pillow",
      "imagehash",
  ]

  [dependency-groups]
  dev = [
      "pytest",
      "httpx",
  ]

  [tool.pytest.ini_options]
  pythonpath = ["src"]
  testpaths = ["tests"]

  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"

  [tool.hatch.build.targets.wheel]
  packages = ["src/pact"]
  ```

  Create `src/pact/__init__.py`:

  ```python
  """Pact — a self-binding commitment engine.

  The agent that holds you to your word: coach until the deadline, auditor at the deadline.
  """

  __version__ = "0.1.0"
  ```

- [ ] **Step 4: Sync deps and run the test (expected PASS)**

  ```
  uv sync --dev
  uv run pytest tests/test_smoke.py::test_package_imports -v
  ```

  Expected: PASS — `1 passed`. `pact` imports because `pythonpath=["src"]` puts `src/` on `sys.path`.

  Sanity-check the whole suite is collectable and green:

  ```
  uv run pytest -q
  ```

  Expected: PASS — `1 passed`. (The `fixed_clock` and `repo` fixtures are defined but unused so far; their lazy imports mean collection does not fail despite `pact.clock` / `pact.repository` not existing yet.)

- [ ] **Step 5: Commit**

  ```
  git add pyproject.toml src/pact/__init__.py tests/conftest.py tests/test_smoke.py
  git commit -m "Task 1: scaffold uv project, pytest config, and shared fixtures"
  ```


### Task 2: Clock (injectable now)

**Files:**
- Create: `src/pact/clock.py`
- Test: `tests/test_clock.py`

Rationale: All Pact lifecycle logic reads an injected `now()` and never calls `datetime.now()` directly (spec §5, §6). This task provides the `Clock` Protocol, a `RealClock` for production (tz-aware UTC), and a `FixedClock` for deterministic tests and the demo "Advance day" harness (§10).

---

- [ ] **Step 1: Write the failing test**

  Create `tests/test_clock.py` with the full test suite. These tests assert: `FixedClock.now()` is stable across calls, `set` replaces the instant, `advance` moves forward by hours/days/minutes (and combinations), `RealClock.now()` returns a timezone-aware UTC datetime, and that both classes structurally satisfy the `Clock` Protocol.

  ```python
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
  ```

- [ ] **Step 2: Run the test (expect FAIL)**

  ```bash
  uv run pytest tests/test_clock.py -v
  ```

  Expected: FAIL — `ModuleNotFoundError: No module named 'pact.clock'` (the module does not exist yet).

- [ ] **Step 3: Write the minimal implementation**

  Create `src/pact/clock.py`. `Clock` is a `typing.Protocol` defining the `now()` seam. `RealClock.now()` returns `datetime.now(timezone.utc)`. `FixedClock` holds a mutable instant with `set` and `advance` per the contract signature (`*, hours=0, days=0, minutes=0`).

  ```python
  from __future__ import annotations

  from datetime import datetime, timedelta, timezone
  from typing import Protocol


  class Clock(Protocol):
      def now(self) -> datetime: ...


  class RealClock:
      def now(self) -> datetime:
          return datetime.now(timezone.utc)


  class FixedClock:
      def __init__(self, current: datetime) -> None:
          self._current = current

      def now(self) -> datetime:
          return self._current

      def set(self, dt: datetime) -> None:
          self._current = dt

      def advance(self, *, hours: float = 0, days: float = 0, minutes: float = 0) -> None:
          self._current = self._current + timedelta(hours=hours, days=days, minutes=minutes)
  ```

- [ ] **Step 4: Run the test (expect PASS)**

  ```bash
  uv run pytest tests/test_clock.py -v
  ```

  Expected: PASS — all 8 tests green.

- [ ] **Step 5: Commit**

  ```bash
  git add src/pact/clock.py tests/test_clock.py
  git commit -m "Add injectable Clock (RealClock + FixedClock)

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
  ```


### Task 3: Config / Settings

**Files:**
- Create: `src/pact/config.py`
- Test: `tests/test_config.py`

This task implements the frozen `Settings` dataclass and `load_settings(env)`, which reads `PACT_*` keys from an injected env mapping (never `os.environ` directly inside logic). Defaults match the contract exactly. Integer keys are parsed with `int()`; a malformed integer raises `ValueError` with a clear message naming the offending key.

---

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py` with full coverage: defaults, full env override, partial override (unset keys keep defaults), empty mapping behaves like defaults, `None` env is accepted, frozen-ness, and bad-int behavior (clear `ValueError`).

```python
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
```

---

- [ ] **Step 2: Run the test (expect FAIL)**

```
uv run pytest tests/test_config.py -v
```

Expected: collection/import error or failures — `ModuleNotFoundError: No module named 'pact.config'` (the module does not exist yet).

---

- [ ] **Step 3: Minimal implementation**

Create `src/pact/config.py` exactly per the frozen contract: a `@dataclass(frozen=True)` `Settings` and `load_settings(env)`. Integer fields are read through a helper that raises a clear `ValueError` naming the key and the bad value.

```python
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
    )
```

Note: `int("")` raises `ValueError`, so blank integer values are caught by the same guard.

---

- [ ] **Step 4: Run the test (expect PASS)**

```
uv run pytest tests/test_config.py -v
```

Expected: all tests pass (defaults, full + partial override, `None` env, frozen-ness, and both bad-int cases).

---

- [ ] **Step 5: Commit**

```
git add src/pact/config.py tests/test_config.py
git commit -m "Add Settings dataclass and load_settings(env) for PACT_* config"
```


### Task 4: Domain models + enums

**Files:**
- Create: `src/pact/models.py`
- Test: `tests/test_models.py`

This task implements all enums (each subclassing `(str, Enum)`) and the Pydantic v2 models — `Rubric`, `Pact`, `Proof`, `Verdict`, `ReasoningTask` — exactly per the frozen contract, including the `stake_amount_cents` `field_validator` enforcing `0 < v <= 50000`.

---

- [ ] **Step 1: Write the failing test**

Create `tests/test_models.py`. These tests build a valid `Pact`/`Rubric`/`Proof`/`Verdict`/`ReasoningTask`, assert the enum membership/values, assert that `stake_amount_cents > 50000` (and `<= 0`) raises `ValidationError`, and round-trip via `model_dump_json` / `model_validate_json`.

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from pact.models import (
    Modality,
    PactStatus,
    PaymentAction,
    Proof,
    ProofStatus,
    Pact,
    ReasoningTask,
    Rubric,
    StakeState,
    TaskStatus,
    TaskType,
    Verdict,
)


def _utc(y, mo, d, h=0, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)


def _rubric() -> Rubric:
    return Rubric(
        modality=Modality.photo,
        must_show=["person mid/post exercise OR gym equipment"],
        reject_if=["stock/watermark", "pure UI screenshot"],
        min_distinct_days=5,
        count_target=5,
        rigor_floor={
            "require_token": True,
            "min_distinct_days": 4,
            "non_negotiable": ["require_token", "server_time_is_truth", "no_duplicates"],
        },
    )


def _pact(**overrides) -> Pact:
    base = dict(
        id="pact_a1b2c3",
        owner="colehaddad40@gmail.com",
        original_prompt="work out 5x this week or $20 to charity",
        title="Work out 5x this week",
        goal="Complete 5 workout sessions on 5 distinct days this week.",
        timezone="America/Los_Angeles",
        deadline_at=_utc(2026, 6, 29, 6, 59, 59),
        target_count=5,
        recommended_stake_cents=2000,
        stake_amount_cents=2000,
        charity_id="world_central_kitchen",
        charity_url="https://wck.org/donate",
        rubric=_rubric(),
        created_at=_utc(2026, 6, 24, 18, 0, 0),
    )
    base.update(overrides)
    return Pact(**base)


def test_enums_are_str_enums_with_expected_members():
    assert isinstance(PactStatus.draft, str)
    assert PactStatus.draft == "draft"
    assert PactStatus.donation_declined == "donation_declined"
    assert StakeState.none == "none"
    assert StakeState.executed == "executed"
    assert ProofStatus.passed == "passed"
    assert ProofStatus.ambiguous == "ambiguous"
    assert Modality.photo == "photo"
    assert Modality.text == "text"
    assert TaskType.judge_proof == "judge_proof"
    assert TaskStatus.pending == "pending"
    assert PaymentAction.none == "none"
    assert PaymentAction.donation_executed == "donation_executed"


def test_rubric_defaults():
    r = _rubric()
    assert r.require_token is True
    assert r.rest_if_injured_counts is True
    assert r.reject_if == ["stock/watermark", "pure UI screenshot"]
    # defaults when omitted
    bare = Rubric(modality=Modality.log, must_show=["a log row"], min_distinct_days=3, count_target=3)
    assert bare.require_token is True
    assert bare.reject_if == []
    assert bare.rigor_floor == {}


def test_build_valid_pact_uses_defaults():
    p = _pact()
    assert p.status == PactStatus.draft
    assert p.stake_state == StakeState.none
    assert p.currency == "usd"
    assert p.distinct_days is True
    assert p.proof_source == "manual"
    assert p.freezes_allowed == 1
    assert p.freezes_used == 0
    assert p.freeze_extension_hours == 24
    assert p.spend_request_id is None
    assert p.started_at is None
    assert p.verdict_at is None
    assert p.rubric.count_target == 5


def test_stake_amount_over_cap_raises():
    with pytest.raises(ValidationError):
        _pact(stake_amount_cents=50001)


def test_stake_amount_at_cap_is_allowed():
    p = _pact(stake_amount_cents=50000)
    assert p.stake_amount_cents == 50000


def test_stake_amount_zero_or_negative_raises():
    with pytest.raises(ValidationError):
        _pact(stake_amount_cents=0)
    with pytest.raises(ValidationError):
        _pact(stake_amount_cents=-1)


def test_build_proof_and_status_enum():
    proof = Proof(
        id="proof_1",
        pact_id="pact_a1b2c3",
        modality=Modality.photo,
        received_at=_utc(2026, 6, 24, 18, 3, 0),
        day_bucket="2026-06-24",
        token_issued="PACT-7Q",
        token_ok=True,
        phash="f0e1",
        status=ProofStatus.passed,
        judge_reason="Token PACT-7Q visible; person on treadmill.",
        judge_checklist={"token": True, "content": True, "not_dup": True},
    )
    assert proof.status == ProofStatus.passed
    assert proof.dup_of is None
    assert proof.artifact_path is None


def test_build_verdict_defaults():
    v = Verdict(
        pact_id="pact_a1b2c3",
        status=PactStatus.failed,
        valid_proof_count=4,
        target_count=5,
        freezes_used=0,
        summary="4 of 5 distinct-day proofs by deadline. Pact failed.",
        proof_ids=["proof_1", "proof_2", "proof_3", "proof_4"],
        honesty_note="Commitment device; proofs judged best-effort, not forensically verified.",
    )
    assert v.payment_action == PaymentAction.none
    assert v.payment_ref is None
    assert v.receipt_artifact_path is None


def test_build_reasoning_task_defaults():
    t = ReasoningTask(
        id="task_1",
        pact_id="pact_a1b2c3",
        type=TaskType.judge_proof,
        input={"token_ok": True, "is_duplicate": False, "content_ok": True, "rubric": {}},
        created_at=_utc(2026, 6, 24, 18, 3, 0),
    )
    assert t.status == TaskStatus.pending
    assert t.result is None
    assert t.claimed_by is None
    assert t.required_capability is None


def test_pact_round_trip_json():
    p = _pact()
    raw = p.model_dump_json()
    restored = Pact.model_validate_json(raw)
    assert restored == p
    assert restored.rubric == p.rubric
    assert restored.deadline_at == p.deadline_at


def test_verdict_round_trip_json():
    v = Verdict(
        pact_id="pact_a1b2c3",
        status=PactStatus.succeeded,
        valid_proof_count=5,
        target_count=5,
        freezes_used=1,
        summary="5 of 5. Pact succeeded.",
        proof_ids=["proof_1"],
        payment_action=PaymentAction.none,
        honesty_note="best-effort",
    )
    assert Verdict.model_validate_json(v.model_dump_json()) == v
```

- [ ] **Step 2: Run the test (expected FAIL)**

```
uv run pytest tests/test_models.py -v
```

Expected: collection/import error — `ModuleNotFoundError: No module named 'pact.models'` (or `ImportError` for the symbols), so every test FAILS. This confirms the test targets code that does not exist yet.

- [ ] **Step 3: Minimal implementation**

Create `src/pact/models.py` with all enums and models per the frozen contract. The `stake_amount_cents` validator enforces `0 < v <= 50000`.

```python
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, field_validator


class PactStatus(str, Enum):
    draft = "draft"
    active = "active"
    evaluating = "evaluating"
    succeeded = "succeeded"
    failed = "failed"
    needs_review = "needs_review"
    canceled_release = "canceled_release"
    canceled_forfeit = "canceled_forfeit"
    donation_pending = "donation_pending"
    donated = "donated"
    donation_failed = "donation_failed"
    donation_declined = "donation_declined"


class StakeState(str, Enum):
    none = "none"
    committed = "committed"
    executing = "executing"
    executed = "executed"
    released = "released"
    declined = "declined"
    error = "error"


class ProofStatus(str, Enum):
    passed = "passed"
    failed = "failed"
    ambiguous = "ambiguous"


class Modality(str, Enum):
    photo = "photo"
    log = "log"
    url = "url"
    file = "file"
    text = "text"


class TaskType(str, Enum):
    draft = "draft"
    judge_proof = "judge_proof"
    coach = "coach"
    verdict = "verdict"


class TaskStatus(str, Enum):
    pending = "pending"
    claimed = "claimed"
    done = "done"
    failed = "failed"


class PaymentAction(str, Enum):
    none = "none"
    donation_executed = "donation_executed"
    donation_failed = "donation_failed"
    donation_declined = "donation_declined"
    cancelled = "cancelled"


class Rubric(BaseModel):
    modality: Modality
    require_token: bool = True
    must_show: list[str]
    reject_if: list[str] = []
    min_distinct_days: int
    count_target: int
    rest_if_injured_counts: bool = True
    rigor_floor: dict = {}


class Pact(BaseModel):
    id: str
    owner: str
    original_prompt: str
    title: str
    goal: str
    timezone: str
    deadline_at: datetime
    target_count: int
    distinct_days: bool = True
    recommended_stake_cents: int
    stake_amount_cents: int
    currency: str = "usd"
    charity_id: str
    charity_url: str
    proof_source: str = "manual"
    freezes_allowed: int = 1
    freezes_used: int = 0
    freeze_extension_hours: int = 24
    rubric: Rubric
    status: PactStatus = PactStatus.draft
    stake_state: StakeState = StakeState.none
    spend_request_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    verdict_at: datetime | None = None

    @field_validator("stake_amount_cents")
    @classmethod
    def _check_stake(cls, v: int) -> int:
        if not (0 < v <= 50000):
            raise ValueError("stake_amount_cents must satisfy 0 < v <= 50000")
        return v


class Proof(BaseModel):
    id: str
    pact_id: str
    modality: Modality
    received_at: datetime
    day_bucket: str
    token_issued: str | None = None
    token_ok: bool = False
    phash: str | None = None
    dup_of: str | None = None
    artifact_path: str | None = None
    status: ProofStatus
    judge_reason: str = ""
    judge_checklist: dict = {}


class Verdict(BaseModel):
    pact_id: str
    status: PactStatus
    valid_proof_count: int
    target_count: int
    freezes_used: int
    summary: str
    proof_ids: list[str]
    payment_action: PaymentAction = PaymentAction.none
    payment_ref: str | None = None
    receipt_artifact_path: str | None = None
    honesty_note: str


class ReasoningTask(BaseModel):
    id: str
    pact_id: str | None
    type: TaskType
    required_capability: str | None = None
    input: dict
    status: TaskStatus = TaskStatus.pending
    result: dict | None = None
    claimed_by: str | None = None
    created_at: datetime
```

- [ ] **Step 4: Run the test (expected PASS)**

```
uv run pytest tests/test_models.py -v
```

Expected: all tests PASS (enum membership, default population, the `0 < v <= 50000` cap rejecting `50001`/`0`/`-1` while accepting `50000`, and both JSON round-trips reconstructing equal models).

- [ ] **Step 5: Commit**

```
git add src/pact/models.py tests/test_models.py
git commit -m "Add Pact domain models and enums with stake validator"
```


### Task 5: SQLite repository

**Files:**
- Create: `src/pact/repository.py`
- Test: `tests/test_repository.py`
- (Depends on earlier tasks: `src/pact/models.py` — `Pact`, `Proof`, `ReasoningTask`, `Verdict`, the enums; `src/pact/clock.py` is not required here but datetimes are timezone-aware per project convention.)

The `Repository` persists each entity to its own table. Each row stores the full model as a `model_dump_json()` TEXT blob in a `data` column, plus a handful of duplicated, indexed columns (`id`, `owner`, `status`, `deadline_at`) used purely for `WHERE`/`ORDER BY` queries. Rows are reconstructed with `Model.model_validate_json(row["data"])`, so the JSON blob is the source of truth and the indexed columns are derived. `deadline_at` is stored as an ISO-8601 string so lexical comparison matches chronological comparison for `due_active_pacts`.

---

- [ ] **Step 1: Write the failing test**

Create `tests/test_repository.py` with the full suite below. It exercises pact round-trip (save/get/update), `list_pacts` filtering by owner, `due_active_pacts` (only `active` pacts at-or-past the `now` cutoff), and proofs/tasks/verdict CRUD. Each test builds models via tiny local factories so the assertions are real and self-contained.

```python
from datetime import datetime, timedelta, timezone

import pytest

from pact.models import (
    Modality,
    Pact,
    PactStatus,
    Proof,
    ProofStatus,
    ReasoningTask,
    Rubric,
    StakeState,
    TaskStatus,
    TaskType,
    Verdict,
    PaymentAction,
)
from pact.repository import Repository

UTC = timezone.utc


def make_rubric() -> Rubric:
    return Rubric(
        modality=Modality.photo,
        must_show=["person mid/post exercise"],
        min_distinct_days=5,
        count_target=5,
    )


def make_pact(
    pact_id: str = "pact_abc123",
    owner: str = "colehaddad40@gmail.com",
    status: PactStatus = PactStatus.draft,
    deadline_at: datetime | None = None,
) -> Pact:
    deadline = deadline_at or datetime(2026, 6, 28, 23, 59, 59, tzinfo=UTC)
    return Pact(
        id=pact_id,
        owner=owner,
        original_prompt="work out 5x this week or $20 to charity",
        title="Work out 5x this week",
        goal="Complete 5 workout sessions on 5 distinct days this week.",
        timezone="America/Los_Angeles",
        deadline_at=deadline,
        target_count=5,
        recommended_stake_cents=2000,
        stake_amount_cents=2000,
        charity_id="world_central_kitchen",
        charity_url="https://wck.org/donate",
        rubric=make_rubric(),
        status=status,
        created_at=datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC),
    )


def make_proof(proof_id: str = "proof_1", pact_id: str = "pact_abc123") -> Proof:
    return Proof(
        id=proof_id,
        pact_id=pact_id,
        modality=Modality.photo,
        received_at=datetime(2026, 6, 24, 18, 3, 0, tzinfo=UTC),
        day_bucket="2026-06-24",
        token_issued="PACT-7Q",
        token_ok=True,
        status=ProofStatus.passed,
        judge_reason="Token visible; person on treadmill.",
        judge_checklist={"token": True, "content": True, "not_dup": True},
    )


def make_task(task_id: str = "task_1", pact_id: str | None = "pact_abc123") -> ReasoningTask:
    return ReasoningTask(
        id=task_id,
        pact_id=pact_id,
        type=TaskType.judge_proof,
        required_capability="vision",
        input={"token_ok": True, "is_duplicate": False, "content_ok": True, "rubric": {}},
        created_at=datetime(2026, 6, 24, 18, 4, 0, tzinfo=UTC),
    )


def make_verdict(pact_id: str = "pact_abc123") -> Verdict:
    return Verdict(
        pact_id=pact_id,
        status=PactStatus.failed,
        valid_proof_count=4,
        target_count=5,
        freezes_used=0,
        summary="4 of 5 distinct-day proofs by deadline. Pact failed.",
        proof_ids=["proof_1", "proof_2"],
        payment_action=PaymentAction.donation_executed,
        honesty_note="Commitment device; proofs judged best-effort, not forensically verified.",
    )


@pytest.fixture
def repo() -> Repository:
    r = Repository.connect(":memory:")
    r.init_schema()
    return r


def test_save_and_get_pact_round_trips(repo: Repository) -> None:
    pact = make_pact()
    repo.save_pact(pact)
    loaded = repo.get_pact(pact.id)
    assert loaded is not None
    assert loaded == pact
    assert loaded.rubric.count_target == 5
    assert loaded.deadline_at == pact.deadline_at
    assert loaded.deadline_at.tzinfo is not None


def test_get_pact_missing_returns_none(repo: Repository) -> None:
    assert repo.get_pact("pact_nope") is None


def test_update_pact_overwrites(repo: Repository) -> None:
    pact = make_pact(status=PactStatus.draft)
    repo.save_pact(pact)
    updated = pact.model_copy(update={"status": PactStatus.active, "stake_state": StakeState.committed})
    repo.update_pact(updated)
    loaded = repo.get_pact(pact.id)
    assert loaded is not None
    assert loaded.status == PactStatus.active
    assert loaded.stake_state == StakeState.committed


def test_list_pacts_filters_by_owner(repo: Repository) -> None:
    repo.save_pact(make_pact(pact_id="pact_a", owner="alice@example.com"))
    repo.save_pact(make_pact(pact_id="pact_b", owner="bob@example.com"))
    repo.save_pact(make_pact(pact_id="pact_c", owner="alice@example.com"))
    alice = repo.list_pacts(owner="alice@example.com")
    assert {p.id for p in alice} == {"pact_a", "pact_c"}
    everyone = repo.list_pacts()
    assert {p.id for p in everyone} == {"pact_a", "pact_b", "pact_c"}


def test_due_active_pacts_only_active_past_deadline(repo: Repository) -> None:
    now = datetime(2026, 6, 28, 0, 0, 0, tzinfo=UTC)
    past = now - timedelta(hours=1)
    future = now + timedelta(hours=1)
    repo.save_pact(make_pact(pact_id="due_active", status=PactStatus.active, deadline_at=past))
    repo.save_pact(make_pact(pact_id="not_due_active", status=PactStatus.active, deadline_at=future))
    repo.save_pact(make_pact(pact_id="past_but_draft", status=PactStatus.draft, deadline_at=past))
    repo.save_pact(make_pact(pact_id="past_but_succeeded", status=PactStatus.succeeded, deadline_at=past))
    due = repo.due_active_pacts(now)
    assert {p.id for p in due} == {"due_active"}


def test_due_active_pacts_includes_exact_deadline(repo: Repository) -> None:
    now = datetime(2026, 6, 28, 0, 0, 0, tzinfo=UTC)
    repo.save_pact(make_pact(pact_id="exact", status=PactStatus.active, deadline_at=now))
    due = repo.due_active_pacts(now)
    assert {p.id for p in due} == {"exact"}


def test_proof_save_and_list(repo: Repository) -> None:
    repo.save_proof(make_proof(proof_id="proof_1", pact_id="pact_abc123"))
    repo.save_proof(make_proof(proof_id="proof_2", pact_id="pact_abc123"))
    repo.save_proof(make_proof(proof_id="proof_x", pact_id="pact_other"))
    proofs = repo.list_proofs("pact_abc123")
    assert {p.id for p in proofs} == {"proof_1", "proof_2"}
    assert all(p.pact_id == "pact_abc123" for p in proofs)
    one = next(p for p in proofs if p.id == "proof_1")
    assert one.judge_checklist == {"token": True, "content": True, "not_dup": True}


def test_task_save_get_update_and_pending(repo: Repository) -> None:
    task = make_task(task_id="task_1")
    repo.save_task(task)
    loaded = repo.get_task("task_1")
    assert loaded is not None
    assert loaded == task
    assert repo.get_task("task_missing") is None

    pending = repo.pending_tasks()
    assert {t.id for t in pending} == {"task_1"}
    pending_vision = repo.pending_tasks(capability="vision")
    assert {t.id for t in pending_vision} == {"task_1"}
    pending_text = repo.pending_tasks(capability="text")
    assert pending_text == []

    done = task.model_copy(
        update={"status": TaskStatus.done, "result": {"status": "failed"}, "claimed_by": "agent_1"}
    )
    repo.update_task(done)
    reloaded = repo.get_task("task_1")
    assert reloaded is not None
    assert reloaded.status == TaskStatus.done
    assert reloaded.result == {"status": "failed"}
    assert repo.pending_tasks() == []


def test_verdict_save_and_get(repo: Repository) -> None:
    repo.save_verdict(make_verdict())
    loaded = repo.get_verdict("pact_abc123")
    assert loaded is not None
    assert loaded == make_verdict()
    assert loaded.payment_action == PaymentAction.donation_executed
    assert repo.get_verdict("pact_none") is None


def test_save_verdict_replaces_existing(repo: Repository) -> None:
    repo.save_verdict(make_verdict())
    updated = make_verdict().model_copy(update={"status": PactStatus.succeeded, "valid_proof_count": 5})
    repo.save_verdict(updated)
    loaded = repo.get_verdict("pact_abc123")
    assert loaded is not None
    assert loaded.status == PactStatus.succeeded
    assert loaded.valid_proof_count == 5
```

- [ ] **Step 2: Run the test (expected FAIL)**

```bash
uv run pytest tests/test_repository.py -v
```

Expected: collection/import error — `ModuleNotFoundError: No module named 'pact.repository'` (the module does not exist yet), so every test ERRORs/FAILs.

- [ ] **Step 3: Minimal implementation**

Create `src/pact/repository.py`. One table per entity; a `data` TEXT column holds `model_dump_json()`; indexed columns (`id`, `owner`, `status`, `deadline_at`) back the queries. Reconstruct with `Model.model_validate_json()`.

```python
from __future__ import annotations

import sqlite3
from datetime import datetime

from pact.models import Pact, PactStatus, Proof, ReasoningTask, Verdict


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    @classmethod
    def connect(cls, path: str) -> "Repository":
        conn = sqlite3.connect(path)
        return cls(conn)

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pacts (
                id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                status TEXT NOT NULL,
                deadline_at TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pacts_owner ON pacts(owner);
            CREATE INDEX IF NOT EXISTS idx_pacts_status ON pacts(status);
            CREATE INDEX IF NOT EXISTS idx_pacts_deadline ON pacts(deadline_at);

            CREATE TABLE IF NOT EXISTS proofs (
                id TEXT PRIMARY KEY,
                pact_id TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_proofs_pact ON proofs(pact_id);

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                pact_id TEXT,
                status TEXT NOT NULL,
                required_capability TEXT,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_capability ON tasks(required_capability);

            CREATE TABLE IF NOT EXISTS verdicts (
                pact_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                data TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    # --- Pact ---

    def save_pact(self, pact: Pact) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO pacts (id, owner, status, deadline_at, data)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                pact.id,
                pact.owner,
                pact.status.value,
                pact.deadline_at.isoformat(),
                pact.model_dump_json(),
            ),
        )
        self.conn.commit()

    def get_pact(self, pact_id: str) -> Pact | None:
        row = self.conn.execute(
            "SELECT data FROM pacts WHERE id = ?", (pact_id,)
        ).fetchone()
        if row is None:
            return None
        return Pact.model_validate_json(row["data"])

    def update_pact(self, pact: Pact) -> None:
        self.save_pact(pact)

    def list_pacts(self, owner: str | None = None) -> list[Pact]:
        if owner is None:
            rows = self.conn.execute("SELECT data FROM pacts").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT data FROM pacts WHERE owner = ?", (owner,)
            ).fetchall()
        return [Pact.model_validate_json(r["data"]) for r in rows]

    def due_active_pacts(self, now: datetime) -> list[Pact]:
        rows = self.conn.execute(
            "SELECT data FROM pacts WHERE status = ? AND deadline_at <= ?",
            (PactStatus.active.value, now.isoformat()),
        ).fetchall()
        return [Pact.model_validate_json(r["data"]) for r in rows]

    # --- Proof ---

    def save_proof(self, proof: Proof) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO proofs (id, pact_id, data)
            VALUES (?, ?, ?)
            """,
            (proof.id, proof.pact_id, proof.model_dump_json()),
        )
        self.conn.commit()

    def list_proofs(self, pact_id: str) -> list[Proof]:
        rows = self.conn.execute(
            "SELECT data FROM proofs WHERE pact_id = ?", (pact_id,)
        ).fetchall()
        return [Proof.model_validate_json(r["data"]) for r in rows]

    # --- ReasoningTask ---

    def save_task(self, task: ReasoningTask) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO tasks (id, pact_id, status, required_capability, data)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                task.id,
                task.pact_id,
                task.status.value,
                task.required_capability,
                task.model_dump_json(),
            ),
        )
        self.conn.commit()

    def get_task(self, task_id: str) -> ReasoningTask | None:
        row = self.conn.execute(
            "SELECT data FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return ReasoningTask.model_validate_json(row["data"])

    def pending_tasks(self, capability: str | None = None) -> list[ReasoningTask]:
        from pact.models import TaskStatus

        if capability is None:
            rows = self.conn.execute(
                "SELECT data FROM tasks WHERE status = ?",
                (TaskStatus.pending.value,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT data FROM tasks WHERE status = ? AND required_capability = ?",
                (TaskStatus.pending.value, capability),
            ).fetchall()
        return [ReasoningTask.model_validate_json(r["data"]) for r in rows]

    def update_task(self, task: ReasoningTask) -> None:
        self.save_task(task)

    # --- Verdict ---

    def save_verdict(self, verdict: Verdict) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO verdicts (pact_id, status, data)
            VALUES (?, ?, ?)
            """,
            (verdict.pact_id, verdict.status.value, verdict.model_dump_json()),
        )
        self.conn.commit()

    def get_verdict(self, pact_id: str) -> Verdict | None:
        row = self.conn.execute(
            "SELECT data FROM verdicts WHERE pact_id = ?", (pact_id,)
        ).fetchone()
        if row is None:
            return None
        return Verdict.model_validate_json(row["data"])
```

- [ ] **Step 4: Run the test (expected PASS)**

```bash
uv run pytest tests/test_repository.py -v
```

Expected: all tests PASS (round-trips equal the originals, `list_pacts` filters by owner, `due_active_pacts` returns only the `active`/at-or-past-deadline pact including the exact-deadline boundary, proofs/tasks/verdict CRUD and `pending_tasks` capability filtering all hold).

- [ ] **Step 5: Commit**

```bash
git add src/pact/repository.py tests/test_repository.py
git commit -m "Add SQLite Repository with json-blob storage and indexed queries

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```


### Task 6: Charity catalog + allowlist

**Files:**
- Create: `src/pact/charities.py`
- Test: `tests/test_charities.py`

This task hardcodes the 10-charity catalog from spec §13 (each entry shaped `{"id","name","donation_url","allowed_domains","category","default_amounts","checkout_kind"}`) and implements `get_charity` plus `is_allowed_url`. The allowlist check parses the URL host with `urllib.parse.urlparse` and accepts it only if the host equals or is a subdomain of one of that charity's `allowed_domains`.

---

- [ ] **Step 1: Write the failing test**

  Create `tests/test_charities.py`:

  ```python
  from pact.charities import CHARITIES, get_charity, is_allowed_url


  def test_catalog_has_ten_unique_charities():
      assert len(CHARITIES) == 10
      ids = [c["id"] for c in CHARITIES]
      assert len(set(ids)) == 10
      assert "world_central_kitchen" in ids


  def test_every_entry_has_required_keys():
      required = {
          "id",
          "name",
          "donation_url",
          "allowed_domains",
          "category",
          "default_amounts",
          "checkout_kind",
      }
      for c in CHARITIES:
          assert required <= set(c.keys()), c["id"]
          assert isinstance(c["allowed_domains"], list)
          assert len(c["allowed_domains"]) >= 1
          assert isinstance(c["default_amounts"], list)


  def test_get_charity_known_id_resolves():
      c = get_charity("world_central_kitchen")
      assert c is not None
      assert c["name"] == "World Central Kitchen"
      assert "wck.org" in c["allowed_domains"]


  def test_get_charity_unknown_id_returns_none():
      assert get_charity("not_a_real_charity") is None


  def test_is_allowed_url_accepts_exact_domain():
      assert is_allowed_url("world_central_kitchen", "https://wck.org/donate") is True


  def test_is_allowed_url_accepts_subdomain():
      assert is_allowed_url("world_central_kitchen", "https://donate.wck.org/now") is True


  def test_is_allowed_url_rejects_off_allowlist_host():
      assert is_allowed_url("world_central_kitchen", "https://evil.example.com/donate") is False


  def test_is_allowed_url_rejects_lookalike_suffix():
      # "notwck.org" must NOT be accepted just because it ends with "wck.org"
      assert is_allowed_url("world_central_kitchen", "https://notwck.org/donate") is False


  def test_is_allowed_url_unknown_charity_is_false():
      assert is_allowed_url("not_a_real_charity", "https://wck.org/donate") is False


  def test_is_allowed_url_missing_host_is_false():
      assert is_allowed_url("world_central_kitchen", "not-a-url") is False
  ```

- [ ] **Step 2: Run the test (expected FAIL)**

  ```
  uv run pytest tests/test_charities.py -v
  ```

  Expected: collection/import error or failures — `ModuleNotFoundError: No module named 'pact.charities'` (the module does not exist yet).

- [ ] **Step 3: Minimal implementation**

  Create `src/pact/charities.py`:

  ```python
  from urllib.parse import urlparse

  CHARITIES: list[dict] = [
      {
          "id": "against_malaria_foundation",
          "name": "Against Malaria Foundation",
          "donation_url": "https://www.againstmalaria.com/donation.aspx",
          "allowed_domains": ["againstmalaria.com", "www.againstmalaria.com"],
          "category": "global_health",
          "default_amounts": [10, 20],
          "checkout_kind": "other",
      },
      {
          "id": "world_central_kitchen",
          "name": "World Central Kitchen",
          "donation_url": "https://wck.org/donate",
          "allowed_domains": ["wck.org", "donate.wck.org"],
          "category": "disaster_food_relief",
          "default_amounts": [10, 20],
          "checkout_kind": "stripe",
      },
      {
          "id": "st_jude",
          "name": "St. Jude Children's Research Hospital",
          "donation_url": "https://www.stjude.org/donate.html",
          "allowed_domains": ["stjude.org", "www.stjude.org"],
          "category": "childrens_health",
          "default_amounts": [10, 20],
          "checkout_kind": "other",
      },
      {
          "id": "doctors_without_borders",
          "name": "Doctors Without Borders",
          "donation_url": "https://donate.doctorswithoutborders.org",
          "allowed_domains": ["doctorswithoutborders.org", "donate.doctorswithoutborders.org"],
          "category": "humanitarian_medical",
          "default_amounts": [10, 20],
          "checkout_kind": "other",
      },
      {
          "id": "american_red_cross",
          "name": "American Red Cross",
          "donation_url": "https://www.redcross.org/donate/donation.html",
          "allowed_domains": ["redcross.org", "www.redcross.org"],
          "category": "disaster_relief",
          "default_amounts": [10, 20],
          "checkout_kind": "other",
      },
      {
          "id": "wikimedia",
          "name": "Wikimedia Foundation",
          "donation_url": "https://donate.wikimedia.org",
          "allowed_domains": ["wikimedia.org", "donate.wikimedia.org"],
          "category": "knowledge_access",
          "default_amounts": [10, 20],
          "checkout_kind": "other",
      },
      {
          "id": "eff",
          "name": "Electronic Frontier Foundation",
          "donation_url": "https://supporters.eff.org/donate",
          "allowed_domains": ["eff.org", "supporters.eff.org"],
          "category": "digital_rights",
          "default_amounts": [10, 20],
          "checkout_kind": "other",
      },
      {
          "id": "trevor_project",
          "name": "The Trevor Project",
          "donation_url": "https://give.thetrevorproject.org",
          "allowed_domains": ["thetrevorproject.org", "give.thetrevorproject.org"],
          "category": "youth_mental_health",
          "default_amounts": [10, 20],
          "checkout_kind": "other",
      },
      {
          "id": "feeding_america",
          "name": "Feeding America",
          "donation_url": "https://www.feedingamerica.org/ways-to-give",
          "allowed_domains": ["feedingamerica.org", "www.feedingamerica.org"],
          "category": "hunger_relief",
          "default_amounts": [10, 20],
          "checkout_kind": "other",
      },
      {
          "id": "charity_water",
          "name": "charity: water",
          "donation_url": "https://www.charitywater.org/donate",
          "allowed_domains": ["charitywater.org", "www.charitywater.org"],
          "category": "clean_water",
          "default_amounts": [10, 20],
          "checkout_kind": "stripe",
      },
  ]


  def get_charity(charity_id: str) -> dict | None:
      for charity in CHARITIES:
          if charity["id"] == charity_id:
              return charity
      return None


  def is_allowed_url(charity_id: str, url: str) -> bool:
      charity = get_charity(charity_id)
      if charity is None:
          return False
      host = urlparse(url).hostname
      if not host:
          return False
      host = host.lower()
      for domain in charity["allowed_domains"]:
          domain = domain.lower()
          if host == domain or host.endswith("." + domain):
              return True
      return False
  ```

- [ ] **Step 4: Run the test (expected PASS)**

  ```
  uv run pytest tests/test_charities.py -v
  ```

  Expected: all tests pass.

- [ ] **Step 5: Commit**

  ```
  git add src/pact/charities.py tests/test_charities.py
  git commit -m "Add charity catalog and URL allowlist (Task 6)"
  ```


### Task 7: Anti-cheat: nonce tokens

**Files:**
- Create: `src/pact/anticheat.py` (add `TokenStore` class)
- Modify: — (no existing file modified; `anticheat.py` is created here, later tasks append `day_bucket`, `count_distinct_valid_days`, `phash_hex`, `find_duplicate`)
- Test: `tests/test_anticheat_token.py`

Implements anti-cheat layer 1 from spec §6: a per-submission single-use nonce token with a TTL, verified against the backend's injected `Clock`. A token verifies exactly once (single-use), fails after its TTL elapses (checked via `clock.advance`), and never verifies against a different `pact_id`.

The `TokenStore` API per the frozen contract:
- `__init__(self, ttl_minutes: int = 10)`
- `issue(self, pact_id: str, clock: Clock) -> str` — returns a short token (e.g. `"PACT-7Q"`); stores `(pact_id, expires_at, used=False)`.
- `verify(self, pact_id: str, token: str, clock: Clock) -> bool` — single-use + not expired; marks the token used on a successful verify.

Depends on `Clock` from `src/pact/clock.py` (`FixedClock` for tests), which is implemented in an earlier task.

---

- [ ] **Step 1: Write the failing test**

  Create `tests/test_anticheat_token.py` with the three behaviors from the task focus: issued token verifies once then fails (used), expired token fails after `clock.advance`, and a wrong `pact_id` fails.

  ```python
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
  ```

- [ ] **Step 2: Run the test (expected FAIL)**

  ```bash
  uv run pytest tests/test_anticheat_token.py -v
  ```

  Expected: FAIL — collection error `ModuleNotFoundError: No module named 'pact.anticheat'` (or `ImportError: cannot import name 'TokenStore'` once the module exists but the class does not). No tests pass yet.

- [ ] **Step 3: Minimal implementation**

  Create `src/pact/anticheat.py` with the `TokenStore` class. Tokens are short, random, uppercase, and prefixed `PACT-` per spec §6. Each entry stores its `pact_id`, the absolute `expires_at` instant (computed from the injected clock + TTL), and a `used` flag. `verify` rejects unknown tokens, wrong-pact tokens, already-used tokens, and expired tokens; on success it flips `used = True` so the token cannot be reused.

  ```python
  from __future__ import annotations

  import secrets
  from dataclasses import dataclass
  from datetime import datetime, timedelta

  from pact.clock import Clock

  _ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous 0/O/1/I


  @dataclass
  class _TokenEntry:
      pact_id: str
      expires_at: datetime
      used: bool = False


  class TokenStore:
      """In-memory single-use nonce tokens with a TTL (anti-cheat layer 1)."""

      def __init__(self, ttl_minutes: int = 10) -> None:
          self._ttl_minutes = ttl_minutes
          self._tokens: dict[str, _TokenEntry] = {}

      def issue(self, pact_id: str, clock: Clock) -> str:
          token = "PACT-" + "".join(secrets.choice(_ALPHABET) for _ in range(2))
          # Avoid a (vanishingly rare) collision with a live token.
          while token in self._tokens:
              token = "PACT-" + "".join(secrets.choice(_ALPHABET) for _ in range(2))
          expires_at = clock.now() + timedelta(minutes=self._ttl_minutes)
          self._tokens[token] = _TokenEntry(pact_id=pact_id, expires_at=expires_at)
          return token

      def verify(self, pact_id: str, token: str, clock: Clock) -> bool:
          entry = self._tokens.get(token)
          if entry is None:
              return False
          if entry.pact_id != pact_id:
              return False
          if entry.used:
              return False
          if clock.now() > entry.expires_at:
              return False
          entry.used = True
          return True
  ```

- [ ] **Step 4: Run the test (expected PASS)**

  ```bash
  uv run pytest tests/test_anticheat_token.py -v
  ```

  Expected: PASS — all five tests green (`test_issued_token_verifies_exactly_once`, `test_expired_token_fails_after_ttl`, `test_token_within_ttl_still_verifies`, `test_wrong_pact_id_fails`, `test_unknown_token_fails`).

- [ ] **Step 5: Commit**

  ```bash
  git add src/pact/anticheat.py tests/test_anticheat_token.py
  git commit -m "Add TokenStore single-use nonce tokens (anti-cheat layer 1)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
  ```


### Task 8: Anti-cheat: server-day distinct counting

Implements layer 2 of the anti-cheat stack (spec §6): the proof's day is the backend `received_at` bucketed into the pact's timezone — never EXIF or user-typed dates — and at most one valid proof counts per calendar day. This kills "dump 5 photos Sunday night."

**Files:**
- Modify: `/Users/chadd_mini/hermes-projects/pact/src/pact/anticheat.py` (add `day_bucket`, `count_distinct_valid_days`)
- Test: `/Users/chadd_mini/hermes-projects/pact/tests/test_anticheat_days.py` (create)

Contract (frozen — match exactly):
- `def day_bucket(received_at: datetime, tz: str) -> str` — `"YYYY-MM-DD"` in the pact timezone (via `zoneinfo`).
- `def count_distinct_valid_days(proofs: list[Proof]) -> int` — distinct `day_bucket` among proofs with `status == ProofStatus.passed`.

Depends on `Proof` and `ProofStatus` from `src/pact/models.py` (Task on models). A `Proof` carries `id, pact_id, modality, received_at, day_bucket, status` among others.

---

- [ ] **Step 1: Write the failing test**

Create `/Users/chadd_mini/hermes-projects/pact/tests/test_anticheat_days.py`:

```python
from datetime import datetime, timezone, timedelta

from pact.anticheat import day_bucket, count_distinct_valid_days
from pact.models import Proof, Modality, ProofStatus


def _proof(proof_id: str, received_at: datetime, tz: str, status: ProofStatus) -> Proof:
    return Proof(
        id=proof_id,
        pact_id="pact_abc123",
        modality=Modality.photo,
        received_at=received_at,
        day_bucket=day_bucket(received_at, tz),
        status=status,
    )


def test_day_bucket_formats_yyyy_mm_dd_in_pact_tz():
    received = datetime(2026, 6, 24, 18, 3, 0, tzinfo=timezone.utc)
    assert day_bucket(received, "UTC") == "2026-06-24"


def test_day_bucket_converts_utc_instant_into_pact_timezone():
    # 06:00 UTC is still the previous calendar day in Los Angeles (UTC-7 in summer).
    received = datetime(2026, 6, 25, 6, 0, 0, tzinfo=timezone.utc)
    assert day_bucket(received, "UTC") == "2026-06-25"
    assert day_bucket(received, "America/Los_Angeles") == "2026-06-24"


def test_day_bucket_tz_boundary_same_instant_different_days():
    # A late-night LA submission and an early-morning UTC submission can be the same
    # UTC instant yet land in different calendar days depending on the pact tz.
    late_night_utc = datetime(2026, 6, 25, 4, 30, 0, tzinfo=timezone.utc)
    assert day_bucket(late_night_utc, "UTC") == "2026-06-25"
    assert day_bucket(late_night_utc, "America/Los_Angeles") == "2026-06-24"


def test_two_passed_proofs_same_calendar_day_count_as_one():
    tz = "America/Los_Angeles"
    morning = datetime(2026, 6, 24, 15, 0, 0, tzinfo=timezone.utc)   # 08:00 LA
    evening = datetime(2026, 6, 25, 1, 0, 0, tzinfo=timezone.utc)    # 18:00 LA, same LA day
    proofs = [
        _proof("proof_1", morning, tz, ProofStatus.passed),
        _proof("proof_2", evening, tz, ProofStatus.passed),
    ]
    assert proofs[0].day_bucket == proofs[1].day_bucket == "2026-06-24"
    assert count_distinct_valid_days(proofs) == 1


def test_distinct_days_counts_each_calendar_day_once():
    tz = "UTC"
    proofs = [
        _proof("proof_1", datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc), tz, ProofStatus.passed),
        _proof("proof_2", datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc), tz, ProofStatus.passed),
        _proof("proof_3", datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc), tz, ProofStatus.passed),
    ]
    assert count_distinct_valid_days(proofs) == 3


def test_failed_and_ambiguous_proofs_excluded_from_count():
    tz = "UTC"
    proofs = [
        _proof("proof_1", datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc), tz, ProofStatus.passed),
        _proof("proof_2", datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc), tz, ProofStatus.failed),
        _proof("proof_3", datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc), tz, ProofStatus.ambiguous),
    ]
    assert count_distinct_valid_days(proofs) == 1


def test_empty_proof_list_counts_zero():
    assert count_distinct_valid_days([]) == 0
```

- [ ] **Step 2: Run the test — expect FAIL**

```
uv run pytest tests/test_anticheat_days.py -v
```

Expected: FAIL (the functions do not exist yet — `ImportError`/`AttributeError` on `day_bucket` / `count_distinct_valid_days`, or `ModuleNotFoundError` if `anticheat.py` has no such symbols).

- [ ] **Step 3: Minimal implementation**

Add to `/Users/chadd_mini/hermes-projects/pact/src/pact/anticheat.py` (imports at top, functions in the module body — do not remove anything already present such as `TokenStore`, `phash_hex`, `find_duplicate`):

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from pact.models import Proof, ProofStatus


def day_bucket(received_at: datetime, tz: str) -> str:
    """Bucket a server timestamp into a 'YYYY-MM-DD' calendar day in the pact timezone.

    Server time is the source of truth (spec §6). The instant is converted into the
    pact's timezone before the date is taken, so the same UTC instant can land on
    different calendar days for different pact timezones.
    """
    local = received_at.astimezone(ZoneInfo(tz))
    return local.strftime("%Y-%m-%d")


def count_distinct_valid_days(proofs: list[Proof]) -> int:
    """Count distinct day_bucket values among proofs that passed judging.

    At most one valid proof counts per calendar day; failed/ambiguous proofs are
    excluded. This enforces the distinct-day criterion for all-or-nothing verdicts.
    """
    valid_days = {
        proof.day_bucket
        for proof in proofs
        if proof.status == ProofStatus.passed
    }
    return len(valid_days)
```

- [ ] **Step 4: Run the test — expect PASS**

```
uv run pytest tests/test_anticheat_days.py -v
```

Expected: PASS (all assertions green; the LA boundary cases and the failed/ambiguous exclusion confirm the gate).

- [ ] **Step 5: Commit**

```
git add src/pact/anticheat.py tests/test_anticheat_days.py
git commit -m "Add server-day distinct counting (anti-cheat layer 2)"
```


### Task 9: Anti-cheat: perceptual-hash dedup

**Files:**
- Modify: `src/pact/anticheat.py` (add `phash_hex`, `find_duplicate`)
- Test: `tests/test_anticheat_phash.py` (create)

Implements perceptual-hash dedup per spec §6.3: compute a pHash for each proof image and flag reuse when Hamming distance to any prior accepted proof is ≤ ~6 (default threshold 6). `phash_hex` wraps `imagehash.phash(Image.open(path))` to a hex string; `find_duplicate` returns the index of the first existing hash within `threshold` Hamming distance, else `None`. Tests build solid-color PIL images in a `tmp_path`, no on-disk fixtures.

- [ ] **Step 1: Write the failing test**

Create `tests/test_anticheat_phash.py`:

```python
from PIL import Image

from pact.anticheat import find_duplicate, phash_hex


def _make_image(path, color, size=(64, 64)):
    img = Image.new("RGB", size, color)
    img.save(path)
    return str(path)


def test_phash_hex_returns_stable_hex_string(tmp_path):
    p = _make_image(tmp_path / "a.png", (10, 120, 200))
    h1 = phash_hex(p)
    h2 = phash_hex(p)
    assert isinstance(h1, str)
    assert h1 == h2
    # hex string: only hexadecimal characters
    assert all(c in "0123456789abcdef" for c in h1)


def test_identical_image_is_duplicate_distance_zero(tmp_path):
    a = _make_image(tmp_path / "a.png", (200, 30, 30))
    b = _make_image(tmp_path / "b.png", (200, 30, 30))
    ha = phash_hex(a)
    hb = phash_hex(b)
    assert ha == hb
    assert find_duplicate(hb, [ha]) == 0


def test_clearly_different_images_are_not_duplicates(tmp_path):
    # A gradient vs a solid color produce distinct perceptual hashes.
    grad = Image.new("L", (64, 64))
    for x in range(64):
        for y in range(64):
            grad.putpixel((x, y), (x * 4) % 256)
    grad_path = tmp_path / "grad.png"
    grad.convert("RGB").save(grad_path)

    solid = _make_image(tmp_path / "solid.png", (0, 0, 0))

    h_grad = phash_hex(str(grad_path))
    h_solid = phash_hex(solid)
    assert h_grad != h_solid
    assert find_duplicate(h_grad, [h_solid]) is None


def test_find_duplicate_returns_first_match_index(tmp_path):
    a = _make_image(tmp_path / "a.png", (50, 50, 50))
    h = phash_hex(a)
    other = phash_hex(_make_image(tmp_path / "b.png", (0, 0, 0)))
    existing = [other, h, h]
    assert find_duplicate(h, existing) == 1


def test_find_duplicate_empty_existing_is_none(tmp_path):
    h = phash_hex(_make_image(tmp_path / "a.png", (7, 7, 7)))
    assert find_duplicate(h, []) is None
```

- [ ] **Step 2: Run the test — expect FAIL**

```bash
uv run pytest tests/test_anticheat_phash.py -v
```

Expected: FAIL — `ImportError`/`AttributeError` because `phash_hex` and `find_duplicate` are not yet defined in `src/pact/anticheat.py` (collection error / `cannot import name 'phash_hex'`).

- [ ] **Step 3: Minimal implementation**

Add to `src/pact/anticheat.py`:

```python
import imagehash
from PIL import Image


def phash_hex(image_path: str) -> str:
    return str(imagehash.phash(Image.open(image_path)))


def find_duplicate(phash: str, existing: list[str], threshold: int = 6) -> int | None:
    target = imagehash.hex_to_hash(phash)
    for i, h in enumerate(existing):
        if (target - imagehash.hex_to_hash(h)) <= threshold:
            return i
    return None
```

- [ ] **Step 4: Run the test — expect PASS**

```bash
uv run pytest tests/test_anticheat_phash.py -v
```

Expected: PASS — all five tests green. Identical images hash equal (distance 0 → index 0); the gradient vs. solid image differ beyond the threshold (→ `None`); `find_duplicate` returns the first matching index and `None` for empty input.

- [ ] **Step 5: Commit**

```bash
git add src/pact/anticheat.py tests/test_anticheat_phash.py
git commit -m "Add perceptual-hash dedup (phash_hex, find_duplicate)"
```


### Task 10: Reasoning provider (test_llm) + tasks

**Files:**
- Create: `src/pact/reasoning.py`
- Test: `tests/test_reasoning.py`

This task implements the brain seam's deterministic stub: the `ReasoningProvider` Protocol, the `make_reasoning_task` factory, and `TestLLMProvider` with the EXACT deterministic dispatch from the contract. Depends on Task earlier work: `src/pact/models.py` (`TaskType`, `TaskStatus`, `ReasoningTask`, `Modality`) and `src/pact/clock.py` (`Clock`, `FixedClock`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_reasoning.py` with complete tests covering: task factory shape, the draft full-rubric dict, the four-way deterministic `judge_proof` rule, and coach pace math.

```python
from datetime import datetime, timezone

from pact.clock import FixedClock
from pact.models import Modality, TaskStatus, TaskType
from pact.reasoning import TestLLMProvider, make_reasoning_task


FIXED = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)


def _clock() -> FixedClock:
    return FixedClock(FIXED)


def test_make_reasoning_task_builds_pending_task():
    clock = _clock()
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_abc123",
        {"token_ok": True},
        clock,
        required_capability="vision",
    )
    assert task.type == TaskType.judge_proof
    assert task.pact_id == "pact_abc123"
    assert task.input == {"token_ok": True}
    assert task.required_capability == "vision"
    assert task.status == TaskStatus.pending
    assert task.result is None
    assert task.claimed_by is None
    assert task.created_at == FIXED
    assert isinstance(task.id, str) and task.id


def test_make_reasoning_task_defaults_capability_none_and_allows_no_pact():
    task = make_reasoning_task(TaskType.draft, None, {"prompt": "x"}, _clock())
    assert task.pact_id is None
    assert task.required_capability is None


def test_provider_capabilities_are_text_and_vision():
    assert TestLLMProvider().capabilities() == {"text", "vision"}


def test_resolve_draft_returns_full_rubric_and_stake():
    provider = TestLLMProvider()
    task = make_reasoning_task(
        TaskType.draft, None, {"prompt": "work out 5x this week"}, _clock()
    )
    result = provider.resolve(task)
    assert result["refused"] is False
    assert isinstance(result["reason"], str)
    for key in (
        "title",
        "goal",
        "timezone",
        "deadline_iso",
        "target_count",
        "recommended_stake_cents",
        "rubric",
    ):
        assert key in result
    assert isinstance(result["recommended_stake_cents"], int)
    assert result["recommended_stake_cents"] > 0
    rubric = result["rubric"]
    for key in (
        "modality",
        "require_token",
        "must_show",
        "reject_if",
        "min_distinct_days",
        "count_target",
        "rest_if_injured_counts",
        "rigor_floor",
    ):
        assert key in rubric
    assert rubric["modality"] in {m.value for m in Modality}
    assert isinstance(rubric["must_show"], list) and rubric["must_show"]
    assert isinstance(rubric["rigor_floor"], dict)


def test_resolve_judge_proof_passes_only_when_all_good():
    provider = TestLLMProvider()
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_abc123",
        {"token_ok": True, "is_duplicate": False, "content_ok": True, "rubric": {}},
        _clock(),
    )
    result = provider.resolve(task)
    assert result["status"] == "passed"
    assert result["checklist"] == {"token": True, "content": True, "not_dup": True}
    assert isinstance(result["reason"], str)


def test_resolve_judge_proof_not_token_is_failed():
    provider = TestLLMProvider()
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_abc123",
        {"token_ok": False, "is_duplicate": False, "content_ok": True, "rubric": {}},
        _clock(),
    )
    result = provider.resolve(task)
    assert result["status"] == "failed"
    assert result["checklist"]["token"] is False


def test_resolve_judge_proof_duplicate_is_failed():
    provider = TestLLMProvider()
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_abc123",
        {"token_ok": True, "is_duplicate": True, "content_ok": True, "rubric": {}},
        _clock(),
    )
    result = provider.resolve(task)
    assert result["status"] == "failed"
    assert result["checklist"]["not_dup"] is False


def test_resolve_judge_proof_bad_content_is_ambiguous():
    provider = TestLLMProvider()
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_abc123",
        {"token_ok": True, "is_duplicate": False, "content_ok": False, "rubric": {}},
        _clock(),
    )
    result = provider.resolve(task)
    assert result["status"] == "ambiguous"
    assert result["checklist"] == {"token": True, "content": False, "not_dup": True}


def test_resolve_coach_message_contains_pace_math():
    provider = TestLLMProvider()
    task = make_reasoning_task(
        TaskType.coach,
        "pact_abc123",
        {"valid": 2, "target": 5, "days_left": 2, "charity": "World Central Kitchen"},
        _clock(),
    )
    result = provider.resolve(task)
    message = result["message"]
    assert "2" in message and "5" in message
    assert "3" in message  # remaining = target - valid
    assert "World Central Kitchen" in message


def test_resolve_verdict_returns_summary():
    provider = TestLLMProvider()
    task = make_reasoning_task(
        TaskType.verdict, "pact_abc123", {"valid": 4, "target": 5}, _clock()
    )
    result = provider.resolve(task)
    assert "4" in result["summary"] and "5" in result["summary"]
```

- [ ] **Step 2: Run the test (expected FAIL)**

```
uv run pytest tests/test_reasoning.py -v
```

Expected: collection/import error — `ModuleNotFoundError: No module named 'pact.reasoning'` (the module does not exist yet), so every test fails.

- [ ] **Step 3: Minimal implementation**

Create `src/pact/reasoning.py`. The `judge_proof` dispatch implements the contract rule verbatim: `passed` IFF (`token_ok` and not `is_duplicate` and `content_ok`); not token → `failed`; elif duplicate → `failed`; elif not content → `ambiguous`. The coach message embeds pace math (`valid`, `target`, remaining, `days_left`, `charity`).

```python
import hashlib
from typing import Protocol

from .clock import Clock
from .models import ReasoningTask, TaskStatus, TaskType


class ReasoningProvider(Protocol):
    def capabilities(self) -> set[str]:
        ...

    def resolve(self, task: ReasoningTask) -> dict:
        ...


def make_reasoning_task(
    type: TaskType,
    pact_id: str | None,
    input: dict,
    clock: Clock,
    required_capability: str | None = None,
) -> ReasoningTask:
    now = clock.now()
    seed = f"{type.value}:{pact_id}:{now.isoformat()}:{sorted(input.items())!r}"
    task_id = "task_" + hashlib.sha1(seed.encode()).hexdigest()[:8]
    return ReasoningTask(
        id=task_id,
        pact_id=pact_id,
        type=type,
        required_capability=required_capability,
        input=input,
        status=TaskStatus.pending,
        result=None,
        claimed_by=None,
        created_at=now,
    )


class TestLLMProvider:
    """Deterministic reasoning stub for demos/tests and the hybrid fallback."""

    def capabilities(self) -> set[str]:
        return {"text", "vision"}

    def resolve(self, task: ReasoningTask) -> dict:
        if task.type == TaskType.draft:
            return self._draft(task.input)
        if task.type == TaskType.judge_proof:
            return self._judge_proof(task.input)
        if task.type == TaskType.coach:
            return self._coach(task.input)
        if task.type == TaskType.verdict:
            return self._verdict(task.input)
        raise ValueError(f"unsupported task type: {task.type}")

    def _draft(self, input: dict) -> dict:
        prompt = str(input.get("prompt", "")).strip()
        if not prompt:
            return {
                "refused": True,
                "reason": "Empty prompt; nothing to commit to.",
                "title": "",
                "goal": "",
                "timezone": "America/Los_Angeles",
                "deadline_iso": "",
                "target_count": 0,
                "recommended_stake_cents": 0,
                "rubric": {},
            }
        rubric = {
            "modality": "photo",
            "require_token": True,
            "must_show": ["clear evidence the committed action was performed"],
            "reject_if": ["stock/watermark", "pure UI screenshot", "missing token"],
            "min_distinct_days": 5,
            "count_target": 5,
            "rest_if_injured_counts": True,
            "rigor_floor": {
                "require_token": True,
                "min_distinct_days": 4,
                "non_negotiable": [
                    "require_token",
                    "server_time_is_truth",
                    "no_duplicates",
                ],
            },
        }
        return {
            "refused": False,
            "reason": "Goal is concrete and checkable.",
            "title": "Commit: " + prompt[:48],
            "goal": "Complete the committed action 5 times on 5 distinct days.",
            "timezone": "America/Los_Angeles",
            "deadline_iso": "2026-06-28T23:59:59-07:00",
            "target_count": 5,
            "recommended_stake_cents": 2000,
            "rubric": rubric,
        }

    def _judge_proof(self, input: dict) -> dict:
        token_ok = bool(input.get("token_ok"))
        is_duplicate = bool(input.get("is_duplicate"))
        content_ok = bool(input.get("content_ok"))
        checklist = {
            "token": token_ok,
            "content": content_ok,
            "not_dup": not is_duplicate,
        }
        if not token_ok:
            status = "failed"
            reason = "Required nonce token not verified; rejecting proof."
        elif is_duplicate:
            status = "failed"
            reason = "Perceptual hash matches a prior proof; duplicate rejected."
        elif not content_ok:
            status = "ambiguous"
            reason = "Token valid but content does not clearly satisfy the rubric."
        else:
            status = "passed"
            reason = "Token verified, content satisfies rubric, no duplicate."
        return {"status": status, "reason": reason, "checklist": checklist}

    def _coach(self, input: dict) -> dict:
        valid = int(input.get("valid", 0))
        target = int(input.get("target", 0))
        days_left = int(input.get("days_left", 0))
        charity = str(input.get("charity", "your chosen charity"))
        remaining = max(target - valid, 0)
        message = (
            f"{valid} of {target} done, {days_left} days left "
            f"— you need {remaining} more to keep your stake out of "
            f"{charity}."
        )
        return {"message": message}

    def _verdict(self, input: dict) -> dict:
        valid = int(input.get("valid", 0))
        target = int(input.get("target", 0))
        outcome = "Pact succeeded." if valid >= target else "Pact failed."
        summary = f"{valid} of {target} valid distinct-day proofs by deadline. {outcome}"
        return {"summary": summary}
```

- [ ] **Step 4: Run the test (expected PASS)**

```
uv run pytest tests/test_reasoning.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```
git add src/pact/reasoning.py tests/test_reasoning.py
git commit -m "Add test_llm reasoning provider and task factory

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```


### Task 11: Payment provider (test_link)

**Files:**
- Modify: `src/pact/payment.py` (Create)
- Test: `tests/test_payment.py` (Create)

Depends on earlier tasks: `src/pact/models.py` (`Pact`, `Rubric`, `Modality`), `src/pact/clock.py` (`FixedClock`), and the `pyproject.toml` with `pythonpath=["src"]`. Run every command from the repo root.

- [ ] **Step 1: Write the failing test**

  Create `tests/test_payment.py`. The tests build a real `Pact` (so the provider can read `pact.id`, `pact.stake_amount_cents`, `pact.charity_id`), then assert the deterministic `provider_ref` and payload contract.

  ```python
  from datetime import datetime, timezone

  from pact.models import Modality, Pact, Rubric
  from pact.payment import PaymentResult, TestLinkProvider


  def _make_pact(
      pact_id: str = "pact_abc123",
      stake_amount_cents: int = 2000,
      charity_id: str = "world_central_kitchen",
  ) -> Pact:
      created = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
      rubric = Rubric(
          modality=Modality.photo,
          must_show=["person mid/post exercise"],
          min_distinct_days=5,
          count_target=5,
      )
      return Pact(
          id=pact_id,
          owner="colehaddad40@gmail.com",
          original_prompt="work out 5x this week or $20 to charity",
          title="Work out 5x this week",
          goal="Complete 5 workout sessions on 5 distinct days.",
          timezone="America/Los_Angeles",
          deadline_at=datetime(2026, 6, 28, 23, 59, 59, tzinfo=timezone.utc),
          target_count=5,
          recommended_stake_cents=2000,
          stake_amount_cents=stake_amount_cents,
          charity_id=charity_id,
          charity_url="https://wck.org/donate",
          rubric=rubric,
          created_at=created,
      )


  def test_payment_result_is_frozen_dataclass():
      result = PaymentResult(
          provider="test_link",
          status="succeeded",
          provider_ref="test_sr_x",
          payload={"k": "v"},
      )
      assert result.provider == "test_link"
      assert result.status == "succeeded"
      assert result.provider_ref == "test_sr_x"
      assert result.payload == {"k": "v"}


  def test_create_donation_returns_succeeded_result():
      provider = TestLinkProvider()
      pact = _make_pact()

      result = provider.create_donation(pact, idempotency_key="pact_abc123:donation")

      assert isinstance(result, PaymentResult)
      assert result.provider == "test_link"
      assert result.status == "succeeded"


  def test_provider_ref_is_deterministic_from_pact_and_amount():
      provider = TestLinkProvider()
      pact = _make_pact(pact_id="pact_abc123", stake_amount_cents=2000)

      first = provider.create_donation(pact, idempotency_key="pact_abc123:donation")
      second = provider.create_donation(pact, idempotency_key="pact_abc123:donation")

      assert first.provider_ref == "test_sr_pact_abc123_2000"
      assert first.provider_ref == second.provider_ref


  def test_provider_ref_varies_with_pact_id_and_amount():
      provider = TestLinkProvider()

      a = provider.create_donation(
          _make_pact(pact_id="pact_one", stake_amount_cents=500),
          idempotency_key="pact_one:donation",
      )
      b = provider.create_donation(
          _make_pact(pact_id="pact_two", stake_amount_cents=2000),
          idempotency_key="pact_two:donation",
      )

      assert a.provider_ref == "test_sr_pact_one_500"
      assert b.provider_ref == "test_sr_pact_two_2000"
      assert a.provider_ref != b.provider_ref


  def test_payload_carries_charity_amount_and_idempotency_key():
      provider = TestLinkProvider()
      pact = _make_pact(
          pact_id="pact_abc123",
          stake_amount_cents=2000,
          charity_id="world_central_kitchen",
      )

      result = provider.create_donation(pact, idempotency_key="pact_abc123:donation")

      assert result.payload == {
          "charity_id": "world_central_kitchen",
          "amount_cents": 2000,
          "idempotency_key": "pact_abc123:donation",
          "mode": "test",
      }
  ```

- [ ] **Step 2: Run the test (expect FAIL)**

  ```bash
  uv run pytest tests/test_payment.py -v
  ```

  Expected: collection/import error or failure — `ModuleNotFoundError: No module named 'pact.payment'` (the module does not exist yet), or `ImportError: cannot import name 'PaymentResult'`. This confirms the tests fail for the right reason before any implementation.

- [ ] **Step 3: Minimal implementation**

  Create `src/pact/payment.py`. Implement the frozen `PaymentResult` dataclass, the `PaymentProvider` Protocol, and `TestLinkProvider.create_donation` returning the exact deterministic `provider_ref` and payload from the contract.

  ```python
  from dataclasses import dataclass
  from typing import Protocol

  from pact.models import Pact


  @dataclass(frozen=True)
  class PaymentResult:
      provider: str
      status: str
      provider_ref: str
      payload: dict


  class PaymentProvider(Protocol):
      def create_donation(self, pact: Pact, idempotency_key: str) -> PaymentResult:
          ...


  class TestLinkProvider:
      """Deterministic, recording-safe payment provider. No network calls."""

      def create_donation(self, pact: Pact, idempotency_key: str) -> PaymentResult:
          return PaymentResult(
              provider="test_link",
              status="succeeded",
              provider_ref=f"test_sr_{pact.id}_{pact.stake_amount_cents}",
              payload={
                  "charity_id": pact.charity_id,
                  "amount_cents": pact.stake_amount_cents,
                  "idempotency_key": idempotency_key,
                  "mode": "test",
              },
          )
  ```

- [ ] **Step 4: Run the test (expect PASS)**

  ```bash
  uv run pytest tests/test_payment.py -v
  ```

  Expected: all 5 tests pass — `test_payment_result_is_frozen_dataclass`, `test_create_donation_returns_succeeded_result`, `test_provider_ref_is_deterministic_from_pact_and_amount`, `test_provider_ref_varies_with_pact_id_and_amount`, `test_payload_carries_charity_amount_and_idempotency_key`.

- [ ] **Step 5: Commit**

  ```bash
  git add src/pact/payment.py tests/test_payment.py
  git commit -m "Add test_link PaymentProvider with deterministic spend-request ref"
  ```


### Task 12: Lifecycle: transitions

**Files:**
- Create: `src/pact/lifecycle.py` (ALLOWED_TRANSITIONS, transition, new_pact_id; plus exception classes TransitionError, PactRefused)
- Test: `tests/test_lifecycle_transitions.py`

This task lays down the lifecycle state-machine skeleton from spec §5: the `ALLOWED_TRANSITIONS` adjacency map, the `transition()` guard that enforces it, and the deterministic `new_pact_id(seed)` helper. Later lifecycle tasks (draft/confirm/submit/settle) build on these three symbols. Define `TransitionError` and `PactRefused` here too since the contract scopes both exceptions to `lifecycle.py` and `transition()` raises `TransitionError`.

Depends on Task(s) defining `src/pact/models.py` (`Pact`, `PactStatus`, plus the supporting models/enums `Pact` requires) and `src/pact/clock.py` (`FixedClock`) being importable.

- [ ] **Step 1: Write the failing test**

  Create `tests/test_lifecycle_transitions.py`. It exercises the four required behaviors: `draft->active` allowed, `active->succeeded` allowed, `succeeded->active` raises `TransitionError`, and `new_pact_id` is deterministic for a seed. A small helper builds a minimal valid `Pact` so we can mutate its `status` and feed it through `transition()`.

  ```python
  from datetime import datetime, timezone

  import pytest

  from pact.clock import FixedClock
  from pact.lifecycle import (
      ALLOWED_TRANSITIONS,
      TransitionError,
      new_pact_id,
      transition,
  )
  from pact.models import Modality, Pact, PactStatus, Rubric, StakeState


  def _make_pact(status: PactStatus = PactStatus.draft) -> Pact:
      clock = FixedClock(datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc))
      rubric = Rubric(
          modality=Modality.photo,
          must_show=["person mid/post exercise"],
          min_distinct_days=5,
          count_target=5,
      )
      return Pact(
          id="pact_test01",
          owner="colehaddad40@gmail.com",
          original_prompt="work out 5x this week or $20 to charity",
          title="Work out 5x this week",
          goal="Complete 5 workout sessions on 5 distinct days this week.",
          timezone="America/Los_Angeles",
          deadline_at=datetime(2026, 6, 28, 23, 59, 59, tzinfo=timezone.utc),
          target_count=5,
          recommended_stake_cents=2000,
          stake_amount_cents=2000,
          charity_id="world_central_kitchen",
          charity_url="https://wck.org/donate",
          rubric=rubric,
          status=status,
          stake_state=StakeState.none,
          created_at=clock.now(),
      )


  def test_draft_to_active_allowed():
      pact = _make_pact(PactStatus.draft)
      result = transition(pact, PactStatus.active)
      assert result.status == PactStatus.active
      assert result is pact


  def test_active_to_succeeded_allowed():
      pact = _make_pact(PactStatus.active)
      result = transition(pact, PactStatus.evaluating)
      assert result.status == PactStatus.evaluating
      result = transition(result, PactStatus.succeeded)
      assert result.status == PactStatus.succeeded


  def test_succeeded_to_active_raises():
      pact = _make_pact(PactStatus.succeeded)
      with pytest.raises(TransitionError):
          transition(pact, PactStatus.active)


  def test_allowed_transitions_is_keyed_by_status():
      assert PactStatus.active in ALLOWED_TRANSITIONS[PactStatus.draft]
      assert PactStatus.succeeded in ALLOWED_TRANSITIONS[PactStatus.evaluating]
      assert ALLOWED_TRANSITIONS[PactStatus.succeeded] == set()


  def test_new_pact_id_deterministic_for_seed():
      first = new_pact_id("work out 5x this week")
      second = new_pact_id("work out 5x this week")
      assert first == second
      assert first.startswith("pact_")
      assert len(first) == len("pact_") + 6


  def test_new_pact_id_differs_by_seed():
      assert new_pact_id("seed-a") != new_pact_id("seed-b")
  ```

- [ ] **Step 2: Run the test — expect FAIL**

  ```
  uv run pytest tests/test_lifecycle_transitions.py -v
  ```

  Expected: collection/import fails with `ModuleNotFoundError: No module named 'pact.lifecycle'` (the module does not exist yet), so every test ERRORs/FAILs. This confirms the test is wired to the not-yet-written symbols.

- [ ] **Step 3: Minimal implementation**

  Create `src/pact/lifecycle.py` with the two exception classes, the `ALLOWED_TRANSITIONS` map drawn from spec §5, the `transition()` guard, and the deterministic `new_pact_id()`. Encode every edge in the §5 diagram: `draft → active|canceled_release|canceled_forfeit`; `active → evaluating|canceled_release|canceled_forfeit`; `evaluating → succeeded|failed|needs_review`; `needs_review → succeeded|failed|evaluating`; `failed → donation_pending`; `canceled_forfeit → donation_pending`; `donation_pending → donated|donation_failed|donation_declined`. Terminal statuses (`succeeded`, `donated`, `donation_failed`, `donation_declined`, `canceled_release`) map to an empty set.

  ```python
  import hashlib

  from pact.models import Pact, PactStatus


  class TransitionError(Exception):
      """Raised when a requested lifecycle transition is not allowed."""


  class PactRefused(Exception):
      """Raised when a draft is refused by the reasoning provider."""


  ALLOWED_TRANSITIONS: dict[PactStatus, set[PactStatus]] = {
      PactStatus.draft: {
          PactStatus.active,
          PactStatus.canceled_release,
          PactStatus.canceled_forfeit,
      },
      PactStatus.active: {
          PactStatus.evaluating,
          PactStatus.canceled_release,
          PactStatus.canceled_forfeit,
      },
      PactStatus.evaluating: {
          PactStatus.succeeded,
          PactStatus.failed,
          PactStatus.needs_review,
      },
      PactStatus.needs_review: {
          PactStatus.succeeded,
          PactStatus.failed,
          PactStatus.evaluating,
      },
      PactStatus.failed: {
          PactStatus.donation_pending,
      },
      PactStatus.canceled_forfeit: {
          PactStatus.donation_pending,
      },
      PactStatus.donation_pending: {
          PactStatus.donated,
          PactStatus.donation_failed,
          PactStatus.donation_declined,
      },
      PactStatus.succeeded: set(),
      PactStatus.canceled_release: set(),
      PactStatus.donated: set(),
      PactStatus.donation_failed: set(),
      PactStatus.donation_declined: set(),
  }


  def transition(pact: Pact, new: PactStatus) -> Pact:
      allowed = ALLOWED_TRANSITIONS.get(pact.status, set())
      if new not in allowed:
          raise TransitionError(
              f"Cannot transition from {pact.status} to {new}; "
              f"allowed: {sorted(s.value for s in allowed)}"
          )
      pact.status = new
      return pact


  def new_pact_id(seed: str) -> str:
      digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
      return "pact_" + digest[:6]
  ```

- [ ] **Step 4: Run the test — expect PASS**

  ```
  uv run pytest tests/test_lifecycle_transitions.py -v
  ```

  Expected: all six tests PASS — `draft->active` and the `active->evaluating->succeeded` chain are allowed, `succeeded->active` raises `TransitionError`, the `ALLOWED_TRANSITIONS` shape checks hold, and `new_pact_id` is deterministic, `pact_`-prefixed, 11 chars long, and seed-sensitive.

- [ ] **Step 5: Commit**

  ```
  git add src/pact/lifecycle.py tests/test_lifecycle_transitions.py
  git commit -m "Add lifecycle transitions, guard, and new_pact_id

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
  ```


### Task 13: Lifecycle: draft / confirm-start / submit-proof

**Files:**
- Modify: `src/pact/lifecycle.py` (add `draft_pact`, `confirm_and_start`, `submit_proof`; `PactRefused`, `new_pact_id`, `transition` already exist from earlier tasks)
- Test: `tests/test_lifecycle_proof.py`

> Depends on earlier tasks: `Clock`/`FixedClock` (Task 1), `Settings`/`load_settings` (Task 2), models incl. `Pact`/`Proof`/`Rubric`/`Modality`/`PactStatus`/`StakeState`/`ProofStatus`/`TaskType` (Task 3), `charities` incl. `get_charity`/`is_allowed_url` (Task 7), `anticheat` incl. `TokenStore`/`day_bucket`/`phash_hex`/`find_duplicate` (Task 8), `reasoning` incl. `TestLLMProvider`/`make_reasoning_task` (Task 9), and `lifecycle` core (`TransitionError`/`PactRefused`/`ALLOWED_TRANSITIONS`/`transition`/`new_pact_id`) from Task 12.

---

- [ ] **Step 1: Write the failing test**

Create `tests/test_lifecycle_proof.py` with full coverage of the three functions and all required failure paths. Uses `TestLLMProvider` + `FixedClock` + `TokenStore`.

```python
from datetime import datetime, timezone

import pytest

from pact.clock import FixedClock
from pact.config import Settings
from pact.models import Modality, PactStatus, ProofStatus, StakeState
from pact.anticheat import TokenStore
from pact.reasoning import TestLLMProvider
from pact.lifecycle import (
    PactRefused,
    draft_pact,
    confirm_and_start,
    submit_proof,
)


def _clock() -> FixedClock:
    return FixedClock(datetime(2026, 6, 24, 18, 0, 0, tzinfo=timezone.utc))


def _settings() -> Settings:
    return Settings()


# ---------- draft_pact ----------

def test_draft_pact_builds_draft_with_clamped_recommended_stake():
    clock = _clock()
    settings = _settings()
    provider = TestLLMProvider()
    pact = draft_pact("work out 5x this week or $20 to charity", provider, clock, settings)

    assert pact.status == PactStatus.draft
    assert pact.stake_state == StakeState.none
    assert pact.original_prompt == "work out 5x this week or $20 to charity"
    # recommended clamped into [min, max]
    assert settings.min_stake_cents <= pact.recommended_stake_cents <= settings.max_stake_cents
    # stake defaults to recommended
    assert pact.stake_amount_cents == pact.recommended_stake_cents
    assert pact.created_at == clock.now()
    assert pact.id.startswith("pact_")
    assert pact.rubric.modality == Modality.photo


def test_draft_pact_refusal_raises_pact_refused():
    clock = _clock()
    settings = _settings()
    provider = TestLLMProvider()
    with pytest.raises(PactRefused):
        # TestLLMProvider draft refuses when the prompt asks for self-harm
        draft_pact("lose 10 pounds every single day no rest", provider, clock, settings)


# ---------- confirm_and_start ----------

def _draft(clock, settings, provider) -> "object":
    return draft_pact("work out 5x this week or $20 to charity", provider, clock, settings)


def test_confirm_and_start_activates_and_freezes_charity():
    clock = _clock()
    settings = _settings()
    provider = TestLLMProvider()
    pact = _draft(clock, settings, provider)

    started = confirm_and_start(pact, 1000, "world_central_kitchen", clock, settings)

    assert started.status == PactStatus.active
    assert started.stake_state == StakeState.committed
    assert started.stake_amount_cents == 1000
    assert started.charity_id == "world_central_kitchen"
    assert started.charity_url  # frozen, non-empty
    assert started.started_at == clock.now()


def test_confirm_and_start_rejects_stake_above_cap():
    clock = _clock()
    settings = _settings()
    provider = TestLLMProvider()
    pact = _draft(clock, settings, provider)

    with pytest.raises(ValueError):
        confirm_and_start(pact, settings.max_stake_cents + 1, "world_central_kitchen", clock, settings)


def test_confirm_and_start_rejects_stake_below_cap():
    clock = _clock()
    settings = _settings()
    provider = TestLLMProvider()
    pact = _draft(clock, settings, provider)

    with pytest.raises(ValueError):
        confirm_and_start(pact, settings.min_stake_cents - 1, "world_central_kitchen", clock, settings)


def test_confirm_and_start_rejects_unknown_charity():
    clock = _clock()
    settings = _settings()
    provider = TestLLMProvider()
    pact = _draft(clock, settings, provider)

    with pytest.raises(ValueError):
        confirm_and_start(pact, 1000, "not_a_real_charity", clock, settings)


# ---------- submit_proof ----------

def _make_image(tmp_path) -> str:
    from PIL import Image

    path = tmp_path / "proof.jpg"
    Image.new("RGB", (64, 64), color=(123, 222, 64)).save(path)
    return str(path)


def test_submit_proof_valid_photo_passes(tmp_path):
    clock = _clock()
    settings = _settings()
    provider = TestLLMProvider()
    tokens = TokenStore()
    pact = confirm_and_start(
        _draft(clock, settings, provider), 1000, "world_central_kitchen", clock, settings
    )
    token = tokens.issue(pact.id, clock)
    image_path = _make_image(tmp_path)

    proof = submit_proof(
        pact,
        Modality.photo,
        token,
        token_in_image=True,
        content_ok=True,
        image_path=image_path,
        tokens=tokens,
        provider=provider,
        clock=clock,
    )

    assert proof.pact_id == pact.id
    assert proof.token_ok is True
    assert proof.dup_of is None
    assert proof.status == ProofStatus.passed
    assert proof.judge_checklist == {"token": True, "content": True, "not_dup": True}
    assert proof.received_at == clock.now()
    assert proof.day_bucket  # computed in pact tz
    assert proof.phash  # computed for a photo
    assert proof.id


def test_submit_proof_invalid_token_fails(tmp_path):
    clock = _clock()
    settings = _settings()
    provider = TestLLMProvider()
    tokens = TokenStore()
    pact = confirm_and_start(
        _draft(clock, settings, provider), 1000, "world_central_kitchen", clock, settings
    )
    image_path = _make_image(tmp_path)

    # never issued -> verify() is False
    proof = submit_proof(
        pact,
        Modality.photo,
        "PACT-XX",
        token_in_image=True,
        content_ok=True,
        image_path=image_path,
        tokens=tokens,
        provider=provider,
        clock=clock,
    )

    assert proof.token_ok is False
    assert proof.status == ProofStatus.failed


def test_submit_proof_duplicate_phash_fails(tmp_path):
    clock = _clock()
    settings = _settings()
    provider = TestLLMProvider()
    tokens = TokenStore()
    pact = confirm_and_start(
        _draft(clock, settings, provider), 1000, "world_central_kitchen", clock, settings
    )
    image_path = _make_image(tmp_path)

    # first valid proof
    token1 = tokens.issue(pact.id, clock)
    first = submit_proof(
        pact, Modality.photo, token1, True, True, image_path,
        tokens, provider, clock,
    )
    assert first.status == ProofStatus.passed

    # resubmit the SAME image -> duplicate phash -> failed
    token2 = tokens.issue(pact.id, clock)
    dup = submit_proof(
        pact, Modality.photo, token2, True, True, image_path,
        tokens, provider, clock,
        prior_phashes=[first.phash],
    )
    assert dup.dup_of == first.phash
    assert dup.status == ProofStatus.failed
```

- [ ] **Step 2: Run the test, expect FAIL**

```
uv run pytest tests/test_lifecycle_proof.py -v
```

Expected: FAIL (collection/import error — `draft_pact`, `confirm_and_start`, and `submit_proof` are not yet defined in `src/pact/lifecycle.py`; the `prior_phashes` parameter does not exist).

- [ ] **Step 3: Minimal implementation**

Append the three functions to `src/pact/lifecycle.py`. Match the frozen signatures exactly; `submit_proof` takes an optional `prior_phashes` list so the caller (API task) can pass prior accepted phashes from the repo.

```python
from datetime import datetime

from pact.clock import Clock
from pact.config import Settings
from pact.models import (
    Modality,
    Pact,
    PactStatus,
    Proof,
    ProofStatus,
    Rubric,
    StakeState,
    TaskType,
)
from pact.anticheat import TokenStore, day_bucket, find_duplicate, phash_hex
from pact.charities import get_charity, is_allowed_url
from pact.reasoning import ReasoningProvider, make_reasoning_task


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def draft_pact(
    prompt: str,
    provider: ReasoningProvider,
    clock: Clock,
    settings: Settings,
) -> Pact:
    task = make_reasoning_task(TaskType.draft, None, {"prompt": prompt}, clock)
    result = provider.resolve(task)
    if result.get("refused"):
        raise PactRefused(result.get("reason", "Pact refused."))

    recommended = _clamp(
        int(result["recommended_stake_cents"]),
        settings.min_stake_cents,
        settings.max_stake_cents,
    )
    rubric = Rubric.model_validate(result["rubric"])
    now = clock.now()
    return Pact(
        id=new_pact_id(prompt + result["deadline_iso"]),
        owner="",
        original_prompt=prompt,
        title=result["title"],
        goal=result["goal"],
        timezone=result["timezone"],
        deadline_at=datetime.fromisoformat(result["deadline_iso"]),
        target_count=int(result["target_count"]),
        recommended_stake_cents=recommended,
        stake_amount_cents=recommended,
        charity_id="",
        charity_url="",
        freezes_allowed=settings.default_freezes,
        freeze_extension_hours=settings.freeze_extension_hours,
        rubric=rubric,
        status=PactStatus.draft,
        stake_state=StakeState.none,
        created_at=now,
    )


def confirm_and_start(
    pact: Pact,
    stake_amount_cents: int,
    charity_id: str,
    clock: Clock,
    settings: Settings,
) -> Pact:
    if not (settings.min_stake_cents <= stake_amount_cents <= settings.max_stake_cents):
        raise ValueError(
            f"stake {stake_amount_cents} outside caps "
            f"[{settings.min_stake_cents}, {settings.max_stake_cents}]"
        )
    charity = get_charity(charity_id)
    if charity is None:
        raise ValueError(f"unknown charity {charity_id!r}")
    charity_url = charity["donation_url"]
    if not is_allowed_url(charity_id, charity_url):
        raise ValueError(f"charity url {charity_url!r} not on allowlist for {charity_id!r}")

    started = pact.model_copy(
        update={
            "stake_amount_cents": stake_amount_cents,
            "charity_id": charity_id,
            "charity_url": charity_url,
            "status": PactStatus.active,
            "stake_state": StakeState.committed,
            "started_at": clock.now(),
        }
    )
    return started


def submit_proof(
    pact: Pact,
    modality: Modality,
    token: str,
    token_in_image: bool,
    content_ok: bool,
    image_path: str | None,
    tokens: TokenStore,
    provider: ReasoningProvider,
    clock: Clock,
    prior_phashes: list[str] | None = None,
) -> Proof:
    now = clock.now()
    token_ok = tokens.verify(pact.id, token, clock)
    bucket = day_bucket(now, pact.timezone)

    phash: str | None = None
    dup_of: str | None = None
    if image_path is not None:
        phash = phash_hex(image_path)
        existing = prior_phashes or []
        idx = find_duplicate(phash, existing)
        if idx is not None:
            dup_of = existing[idx]

    task = make_reasoning_task(
        TaskType.judge_proof,
        pact.id,
        {
            "token_ok": token_ok,
            "is_duplicate": dup_of is not None,
            "content_ok": content_ok,
            "rubric": pact.rubric.model_dump(),
        },
        clock,
    )
    result = provider.resolve(task)

    return Proof(
        id=new_pact_id(pact.id + token + now.isoformat()).replace("pact_", "proof_"),
        pact_id=pact.id,
        modality=modality,
        received_at=now,
        day_bucket=bucket,
        token_issued=token,
        token_ok=token_ok,
        phash=phash,
        dup_of=dup_of,
        artifact_path=image_path,
        status=ProofStatus(result["status"]),
        judge_reason=result["reason"],
        judge_checklist=result["checklist"],
    )
```

- [ ] **Step 4: Run the test, expect PASS**

```
uv run pytest tests/test_lifecycle_proof.py -v
```

Expected: PASS (all 9 tests green — draft clamp + refusal, confirm-start activation + 3 validation errors, valid/invalid-token/duplicate proof paths).

- [ ] **Step 5: Commit**

```
git add src/pact/lifecycle.py tests/test_lifecycle_proof.py
git commit -m "Add lifecycle draft/confirm-start/submit-proof with anti-cheat + judge"
```


### Task 14: Lifecycle: freeze + cancel

**Files:**
- Modify: `src/pact/lifecycle.py`
- Test: `tests/test_lifecycle_freeze_cancel.py` (Create)

This task assumes earlier tasks established `src/pact/lifecycle.py` with `TransitionError`, `ALLOWED_TRANSITIONS`, `transition`, `new_pact_id`, `draft_pact`, and `confirm_and_start`. We add `spend_freeze` and `cancel`. Per the contract: `spend_freeze` raises if `freezes_used >= freezes_allowed`, else moves `deadline_at` forward by `freeze_extension_hours` and increments `freezes_used`. `cancel` reads the injected clock — within the cooling-off window (`now <= started_at + cooling_off_minutes`) it goes to `canceled_release` with `stake_state` released; after the window it goes to `canceled_forfeit` then `donation_pending`.

- [ ] **Step 1: Write the failing test**

  Create `tests/test_lifecycle_freeze_cancel.py`:

  ```python
  from datetime import datetime, timedelta, timezone

  import pytest

  from pact.clock import FixedClock
  from pact.config import Settings
  from pact.lifecycle import cancel, spend_freeze
  from pact.models import Pact, PactStatus, Rubric, StakeState


  def _rubric() -> Rubric:
      return Rubric(
          modality="photo",
          must_show=["dumbbell"],
          min_distinct_days=3,
          count_target=5,
      )


  def _active_pact(*, started_at: datetime, deadline_at: datetime, clock: FixedClock) -> Pact:
      return Pact(
          id="pact_abc123",
          owner="owner@example.com",
          original_prompt="do the thing",
          title="Do the thing",
          goal="5 workouts",
          timezone="America/New_York",
          deadline_at=deadline_at,
          target_count=5,
          recommended_stake_cents=1000,
          stake_amount_cents=1000,
          charity_id="redcross",
          charity_url="https://www.redcross.org/donate",
          freezes_allowed=1,
          freezes_used=0,
          freeze_extension_hours=24,
          rubric=_rubric(),
          status=PactStatus.active,
          stake_state=StakeState.committed,
          created_at=clock.now(),
          started_at=started_at,
      )


  def test_spend_freeze_moves_deadline_and_increments_used():
      start = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
      clock = FixedClock(start)
      deadline = start + timedelta(days=2)
      pact = _active_pact(started_at=start, deadline_at=deadline, clock=clock)

      result = spend_freeze(pact, clock)

      assert result.freezes_used == 1
      assert result.deadline_at == deadline + timedelta(hours=24)
      assert result.status == PactStatus.active


  def test_second_freeze_when_only_one_allowed_raises():
      start = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
      clock = FixedClock(start)
      deadline = start + timedelta(days=2)
      pact = _active_pact(started_at=start, deadline_at=deadline, clock=clock)

      pact = spend_freeze(pact, clock)
      assert pact.freezes_used == 1

      with pytest.raises(Exception):
          spend_freeze(pact, clock)


  def test_cancel_within_cooling_off_releases_no_donation():
      start = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
      clock = FixedClock(start)
      deadline = start + timedelta(days=2)
      pact = _active_pact(started_at=start, deadline_at=deadline, clock=clock)
      settings = Settings()  # cooling_off_minutes default 60

      clock.advance(minutes=30)  # still inside the 60-minute window
      result = cancel(pact, clock, settings)

      assert result.status == PactStatus.canceled_release
      assert result.stake_state == StakeState.released


  def test_cancel_after_cooling_off_forfeits_donation_pending():
      start = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
      clock = FixedClock(start)
      deadline = start + timedelta(days=2)
      pact = _active_pact(started_at=start, deadline_at=deadline, clock=clock)
      settings = Settings()  # cooling_off_minutes default 60

      clock.advance(minutes=90)  # past the 60-minute window
      result = cancel(pact, clock, settings)

      assert result.status == PactStatus.donation_pending
      assert result.stake_state != StakeState.released
  ```

- [ ] **Step 2: Run the test — expect FAIL**

  ```bash
  uv run pytest tests/test_lifecycle_freeze_cancel.py -v
  ```

  Expected: FAIL — `ImportError: cannot import name 'cancel'` / `'spend_freeze'` from `pact.lifecycle` (functions not yet defined).

- [ ] **Step 3: Minimal implementation**

  Add to `src/pact/lifecycle.py` (imports `timedelta`, `Clock`, `Settings`, `Pact`, `PactStatus`, `StakeState`, and `transition` are assumed present from earlier tasks; add any missing import shown here):

  ```python
  from datetime import timedelta

  from pact.clock import Clock
  from pact.config import Settings
  from pact.models import Pact, PactStatus, StakeState


  def spend_freeze(pact: Pact, clock: Clock) -> Pact:
      if pact.freezes_used >= pact.freezes_allowed:
          raise TransitionError(
              f"no freezes left: used {pact.freezes_used} of {pact.freezes_allowed}"
          )
      pact.deadline_at = pact.deadline_at + timedelta(hours=pact.freeze_extension_hours)
      pact.freezes_used += 1
      return pact


  def cancel(pact: Pact, clock: Clock, settings: Settings) -> Pact:
      now = clock.now()
      cooling_off_end = pact.started_at + timedelta(minutes=settings.cooling_off_minutes)
      if now <= cooling_off_end:
          pact = transition(pact, PactStatus.canceled_release)
          pact.stake_state = StakeState.released
          return pact
      pact = transition(pact, PactStatus.canceled_forfeit)
      pact = transition(pact, PactStatus.donation_pending)
      return pact
  ```

  Ensure `ALLOWED_TRANSITIONS` (from an earlier task) permits `active -> {canceled_release, canceled_forfeit}` and `canceled_forfeit -> donation_pending`. If those edges are missing, add them to the `ALLOWED_TRANSITIONS` dict so `transition` does not raise:

  ```python
  ALLOWED_TRANSITIONS[PactStatus.active].update(
      {PactStatus.canceled_release, PactStatus.canceled_forfeit}
  )
  ALLOWED_TRANSITIONS.setdefault(PactStatus.canceled_forfeit, set()).add(
      PactStatus.donation_pending
  )
  ```

- [ ] **Step 4: Run the test — expect PASS**

  ```bash
  uv run pytest tests/test_lifecycle_freeze_cancel.py -v
  ```

  Expected: PASS — all four tests green (`test_spend_freeze_moves_deadline_and_increments_used`, `test_second_freeze_when_only_one_allowed_raises`, `test_cancel_within_cooling_off_releases_no_donation`, `test_cancel_after_cooling_off_forfeits_donation_pending`).

- [ ] **Step 5: Commit**

  ```bash
  git add src/pact/lifecycle.py tests/test_lifecycle_freeze_cancel.py
  git commit -m "Add lifecycle freeze and cancel (cooling-off release vs forfeit)"
  ```


### Task 15: Lifecycle: settle (verdict + charge-on-fail + idempotency)

**Files:**
- Modify: `src/pact/lifecycle.py` (add `settle`, `submit_dispute`)
- Test: `tests/test_lifecycle_settle.py` (create)

Depends on earlier tasks: `src/pact/models.py` (Pact, Proof, Verdict, PactStatus, StakeState, ProofStatus, PaymentAction), `src/pact/payment.py` (PaymentProvider, PaymentResult, TestLinkProvider), `src/pact/anticheat.py` (`count_distinct_valid_days`), `src/pact/clock.py` (FixedClock), and `src/pact/lifecycle.py` (`transition`, `ALLOWED_TRANSITIONS`, `new_pact_id`) which must already exist.

---

- [ ] **Step 1: Write the failing test**

Create `tests/test_lifecycle_settle.py`. Uses a spy `PaymentProvider` that counts `create_donation` calls so the "zero calls on success" and "exactly one donation on fail" guarantees are asserted directly.

```python
from datetime import datetime, timedelta, timezone

import pytest

from pact.clock import FixedClock
from pact.lifecycle import settle, submit_dispute
from pact.models import (
    PactStatus,
    StakeState,
    PaymentAction,
    ProofStatus,
    Modality,
    Pact,
    Proof,
    Rubric,
)
from pact.payment import PaymentResult, TestLinkProvider


class SpyPaymentProvider:
    """Counts create_donation calls; delegates to a real TestLinkProvider."""

    def __init__(self):
        self.calls = 0
        self._inner = TestLinkProvider()

    def create_donation(self, pact: Pact, idempotency_key: str) -> PaymentResult:
        self.calls += 1
        self.last_idempotency_key = idempotency_key
        return self._inner.create_donation(pact, idempotency_key)


def _rubric() -> Rubric:
    return Rubric(
        modality=Modality.photo,
        must_show=["evidence of the activity"],
        min_distinct_days=3,
        count_target=3,
    )


def _pact(clock: FixedClock, target: int = 3) -> Pact:
    now = clock.now()
    return Pact(
        id="pact_abc123",
        owner="colehaddad40@gmail.com",
        original_prompt="do the thing 3x or $5 to charity",
        title="Do the thing 3x",
        goal="Complete the thing on 3 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=now,
        target_count=target,
        distinct_days=True,
        recommended_stake_cents=500,
        stake_amount_cents=500,
        charity_id="world_central_kitchen",
        charity_url="https://wck.org/donate",
        rubric=_rubric(),
        status=PactStatus.active,
        stake_state=StakeState.committed,
        created_at=now,
        started_at=now,
    )


def _proof(idx: int, day: str, status: ProofStatus, received: datetime) -> Proof:
    return Proof(
        id=f"proof_{idx}",
        pact_id="pact_abc123",
        modality=Modality.photo,
        received_at=received,
        day_bucket=day,
        token_ok=True,
        status=status,
    )


def _passing_proofs(n: int, base: datetime) -> list[Proof]:
    out = []
    for i in range(n):
        day = f"2026-06-2{i}"  # distinct day buckets 2026-06-20..2026-06-2n
        out.append(_proof(i, day, ProofStatus.passed, base + timedelta(days=i)))
    return out


def test_success_makes_zero_payment_calls_and_releases_stake():
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    pact = _pact(clock, target=3)
    proofs = _passing_proofs(3, datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc))
    payment = SpyPaymentProvider()

    new_pact, verdict = settle(pact, proofs, clock, payment)

    assert new_pact.status == PactStatus.succeeded
    assert new_pact.stake_state == StakeState.released
    assert new_pact.spend_request_id is None
    assert payment.calls == 0  # provably zero link-cli calls on success
    assert verdict.status == PactStatus.succeeded
    assert verdict.valid_proof_count == 3
    assert verdict.target_count == 3
    assert verdict.payment_action == PaymentAction.none
    assert verdict.payment_ref is None
    assert new_pact.verdict_at == clock.now()


def test_failure_executes_donation_exactly_once():
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    pact = _pact(clock, target=3)
    proofs = _passing_proofs(2, datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc))
    payment = SpyPaymentProvider()

    new_pact, verdict = settle(pact, proofs, clock, payment)

    assert new_pact.status == PactStatus.donated
    assert payment.calls == 1
    assert payment.last_idempotency_key == "pact_abc123:donation"
    assert new_pact.spend_request_id == f"test_sr_pact_abc123_{pact.stake_amount_cents}"
    assert verdict.status == PactStatus.failed
    assert verdict.valid_proof_count == 2
    assert verdict.payment_action == PaymentAction.donation_executed
    assert verdict.payment_ref == new_pact.spend_request_id


def test_settle_is_idempotent_no_second_donation():
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    pact = _pact(clock, target=3)
    proofs = _passing_proofs(1, datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc))
    payment = SpyPaymentProvider()

    p1, v1 = settle(pact, proofs, clock, payment)
    assert payment.calls == 1
    first_ref = p1.spend_request_id

    p2, v2 = settle(p1, proofs, clock, payment)

    assert payment.calls == 1  # NO second donation
    assert p2.status == PactStatus.donated
    assert p2.spend_request_id == first_ref
    assert v2.payment_ref == first_ref
    assert v2.status == PactStatus.failed


def test_dispute_reruns_settle_exactly_once_then_final():
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    pact = _pact(clock, target=3)
    base = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
    proofs = _passing_proofs(2, base)
    payment = SpyPaymentProvider()

    failed_pact, failed_verdict = settle(pact, proofs, clock, payment)
    assert failed_pact.status == PactStatus.donated
    assert payment.calls == 1

    # Dispute supplies a third valid distinct-day proof -> success on re-run.
    extra = _proof(99, "2026-06-25", ProofStatus.passed,
                   datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc))
    disputed = proofs + [extra]

    dp1, dv1 = submit_dispute(failed_pact, disputed, clock, payment)
    assert dp1.status == PactStatus.succeeded
    assert dv1.status == PactStatus.succeeded
    assert dv1.valid_proof_count == 3

    # Second dispute is rejected: the window is single-use, result already final.
    with pytest.raises(Exception):
        submit_dispute(dp1, disputed, clock, payment)
```

- [ ] **Step 2: Run the test (expected FAIL)**

```
uv run pytest tests/test_lifecycle_settle.py -v
```

Expected: collection/import or attribute failure — `ImportError: cannot import name 'settle'` / `'submit_dispute'` from `pact.lifecycle` (functions not defined yet).

- [ ] **Step 3: Minimal implementation**

Append to `src/pact/lifecycle.py` (do not remove existing `transition`, `ALLOWED_TRANSITIONS`, `new_pact_id`, etc.). Add the imports near the top if not already present.

```python
from pact.anticheat import count_distinct_valid_days
from pact.clock import Clock
from pact.models import (
    Pact,
    PactStatus,
    PaymentAction,
    Proof,
    ProofStatus,
    StakeState,
    Verdict,
)
from pact.payment import PaymentProvider

_TERMINAL_STATUSES = {
    PactStatus.succeeded,
    PactStatus.donated,
    PactStatus.donation_failed,
    PactStatus.donation_declined,
    PactStatus.canceled_release,
    PactStatus.canceled_forfeit,
}


def _valid_count(pact: Pact, proofs: list[Proof]) -> int:
    if pact.distinct_days:
        return count_distinct_valid_days(proofs)
    return sum(1 for p in proofs if p.status == ProofStatus.passed)


def _build_verdict(
    pact: Pact,
    proofs: list[Proof],
    valid: int,
    payment_action: PaymentAction,
    payment_ref: str | None,
) -> Verdict:
    if pact.status == PactStatus.succeeded:
        summary = (
            f"{valid} of {pact.target_count} valid proofs by deadline. Pact succeeded."
        )
    else:
        summary = (
            f"{valid} of {pact.target_count} valid proofs by deadline. Pact failed."
        )
    return Verdict(
        pact_id=pact.id,
        status=pact.status,
        valid_proof_count=valid,
        target_count=pact.target_count,
        freezes_used=pact.freezes_used,
        summary=summary,
        proof_ids=[p.id for p in proofs],
        payment_action=payment_action,
        payment_ref=payment_ref,
        honesty_note=(
            "Commitment device; proofs judged best-effort, not forensically verified."
        ),
    )


def settle(
    pact: Pact,
    proofs: list[Proof],
    clock: Clock,
    payment: PaymentProvider,
) -> tuple[Pact, Verdict]:
    now = clock.now()

    # Idempotent: a pact already in a terminal donation/success state is returned
    # unchanged together with a rebuilt verdict reflecting the prior payment.
    if pact.status in _TERMINAL_STATUSES:
        valid = _valid_count(pact, proofs)
        if pact.spend_request_id is not None:
            action = PaymentAction.donation_executed
            ref = pact.spend_request_id
        elif pact.status == PactStatus.succeeded:
            action = PaymentAction.none
            ref = None
        else:
            action = PaymentAction.none
            ref = pact.spend_request_id
        return pact, _build_verdict(pact, proofs, valid, action, ref)

    valid = _valid_count(pact, proofs)

    if valid >= pact.target_count:
        pact.status = PactStatus.succeeded
        pact.stake_state = StakeState.released
        pact.verdict_at = now
        # SUCCESS: no payment call, no spend_request_id.
        return pact, _build_verdict(pact, proofs, valid, PaymentAction.none, None)

    # FAIL path. Charge-on-fail, exactly once, guarded by spend_request_id.
    pact.status = PactStatus.failed
    if pact.spend_request_id is None:
        pact.status = PactStatus.donation_pending
        result = payment.create_donation(pact, f"{pact.id}:donation")
        pact.spend_request_id = result.provider_ref
        pact.stake_state = StakeState.executed
        pact.status = PactStatus.donated
    pact.verdict_at = now
    return pact, _build_verdict(
        pact, proofs, valid, PaymentAction.donation_executed, pact.spend_request_id
    )


def submit_dispute(
    pact: Pact,
    proofs: list[Proof],
    clock: Clock,
    payment: PaymentProvider,
) -> tuple[Pact, Verdict]:
    # A dispute is allowed exactly once: only a failed/donated pact may be disputed,
    # and a successful re-run (or an already-disputed pact) closes the window for good.
    if pact.status not in {
        PactStatus.failed,
        PactStatus.donation_pending,
        PactStatus.donated,
        PactStatus.donation_failed,
        PactStatus.donation_declined,
    }:
        raise TransitionError(
            f"dispute not allowed from status {pact.status}"
        )

    valid = _valid_count(pact, proofs)
    if valid >= pact.target_count:
        # Extra proof clears the bar -> overturn to success, final.
        pact.status = PactStatus.succeeded
        pact.stake_state = StakeState.released
        pact.verdict_at = clock.now()
        return pact, _build_verdict(pact, proofs, valid, PaymentAction.none, None)

    # Still short: donation already executed once; re-affirm the failed verdict, final.
    pact.verdict_at = clock.now()
    action = (
        PaymentAction.donation_executed
        if pact.spend_request_id is not None
        else PaymentAction.none
    )
    return pact, _build_verdict(pact, proofs, valid, action, pact.spend_request_id)
```

Notes for the implementer:
- `settle` mutates and returns the same `Pact` instance per the contract signature; success sets `stake_state=released` and never touches `payment`.
- The single-donation guard is `pact.spend_request_id is None` — once set (whether by this settle or a prior one) no second `create_donation` fires, which is exactly what `test_settle_is_idempotent_no_second_donation` checks.
- `TransitionError` is already defined earlier in this module (Task on `transition`); reuse it for the closed dispute window.

- [ ] **Step 4: Run the test (expected PASS)**

```
uv run pytest tests/test_lifecycle_settle.py -v
```

Expected: 4 passed — success path makes zero payment calls with `spend_request_id is None`; failure executes the donation once with idempotency key `pact_abc123:donation`; a second `settle` adds no donation; the dispute re-runs settle exactly once and the second dispute raises.

- [ ] **Step 5: Commit**

```
git add src/pact/lifecycle.py tests/test_lifecycle_settle.py
git commit -m "Add settle() verdict with charge-on-fail idempotency and single dispute re-run"
```


### Task 16: Lifecycle: startup reconciliation

**Files:**
- Modify: `src/pact/lifecycle.py` (add `reconcile_on_startup`)
- Test: `tests/test_reconcile.py` (create)

This task adds the startup/ticker sweep described in spec §5 ("On startup, a reconciliation sweep settles any `active` pact past its deadline... even if the user ghosts"). It depends on earlier tasks: `Repository.due_active_pacts` / `list_proofs` / `update_pact` / `save_verdict` / `get_verdict` (Task: repository), `settle` (Task: settle), `TestLinkProvider` (Task: payment), `FixedClock` (Task: clock), and the model layer. `reconcile_on_startup` is a thin loop: for each due active pact it loads proofs, calls `settle`, then persists the returned pact and verdict. Idempotency is inherited from `settle` (terminal pacts with an existing verdict are returned unchanged), so a second sweep — or a restart mid-pact — moves no extra money.

- [ ] **Step 1: Write the failing test**

  Create `tests/test_reconcile.py`. The first test seeds one `active` pact whose deadline is in the past, advances the clock, runs `reconcile_on_startup`, and asserts it settled to `failed`/`donated` with a donation. The second test proves an already-terminal pact is untouched and that a second reconcile is a no-op (ghosting + restart safety).

  ```python
  from datetime import datetime, timedelta, timezone

  from pact.charities import CHARITIES
  from pact.clock import FixedClock
  from pact.config import Settings
  from pact.lifecycle import reconcile_on_startup
  from pact.models import (
      Modality,
      Pact,
      PactStatus,
      PaymentAction,
      ProofStatus,
      Proof,
      Rubric,
      StakeState,
  )
  from pact.payment import TestLinkProvider
  from pact.repository import Repository


  def _rubric() -> Rubric:
      return Rubric(
          modality=Modality.photo,
          must_show=["person mid-exercise"],
          min_distinct_days=2,
          count_target=2,
      )


  def _active_pact(pact_id: str, created_at: datetime, deadline_at: datetime) -> Pact:
      charity = CHARITIES[0]
      return Pact(
          id=pact_id,
          owner="colehaddad40@gmail.com",
          original_prompt="work out 2x or $5 to charity",
          title="Work out 2x",
          goal="Complete 2 workout sessions on 2 distinct days.",
          timezone="America/Los_Angeles",
          deadline_at=deadline_at,
          target_count=2,
          distinct_days=True,
          recommended_stake_cents=500,
          stake_amount_cents=500,
          charity_id=charity["id"],
          charity_url=charity["donation_url"],
          freezes_allowed=1,
          rubric=_rubric(),
          status=PactStatus.active,
          stake_state=StakeState.committed,
          created_at=created_at,
          started_at=created_at,
      )


  def _repo() -> Repository:
      repo = Repository.connect(":memory:")
      repo.init_schema()
      return repo


  def test_reconcile_settles_ghosted_pact_to_failed_donation():
      start = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
      clock = FixedClock(start)
      repo = _repo()
      deadline = start + timedelta(days=3)
      pact = _active_pact("pact_ghost", start, deadline)
      repo.save_pact(pact)

      # Deadline passes with zero proofs submitted.
      clock.advance(days=4)
      settled = reconcile_on_startup(repo, clock, TestLinkProvider())

      assert len(settled) == 1
      saved = repo.get_pact("pact_ghost")
      assert saved.status == PactStatus.donated
      assert saved.stake_state == StakeState.committed
      assert saved.spend_request_id == "test_sr_pact_ghost_500"

      verdict = repo.get_verdict("pact_ghost")
      assert verdict is not None
      assert verdict.status == PactStatus.donated
      assert verdict.valid_proof_count == 0
      assert verdict.target_count == 2
      assert verdict.payment_action == PaymentAction.donation_executed
      assert verdict.payment_ref == "test_sr_pact_ghost_500"


  def test_reconcile_leaves_terminal_pacts_untouched_and_is_idempotent():
      start = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
      clock = FixedClock(start)
      repo = _repo()
      payment = TestLinkProvider()

      # An already-succeeded terminal pact must never be reopened.
      done = _active_pact("pact_done", start, start - timedelta(hours=1))
      done.status = PactStatus.succeeded
      done.stake_state = StakeState.released
      done.verdict_at = start
      repo.save_pact(done)

      # A live active pact whose deadline is still in the future is not due.
      future = _active_pact("pact_future", start, start + timedelta(days=5))
      repo.save_pact(future)

      # A ghosted active pact that IS due.
      ghost = _active_pact("pact_ghost2", start, start - timedelta(hours=1))
      repo.save_pact(ghost)

      first = reconcile_on_startup(repo, clock, payment)
      assert {p.id for p in first} == {"pact_ghost2"}

      assert repo.get_pact("pact_done").status == PactStatus.succeeded
      assert repo.get_pact("pact_done").stake_state == StakeState.released
      assert repo.get_pact("pact_future").status == PactStatus.active
      assert repo.get_pact("pact_ghost2").status == PactStatus.donated

      ref_after_first = repo.get_pact("pact_ghost2").spend_request_id
      assert ref_after_first == "test_sr_pact_ghost2_500"

      # Restart safety: a second sweep settles nothing new and moves no money.
      second = reconcile_on_startup(repo, clock, payment)
      assert second == []
      assert repo.get_pact("pact_ghost2").spend_request_id == ref_after_first
      assert repo.get_verdict("pact_ghost2").payment_ref == ref_after_first
  ```

- [ ] **Step 2: Run the test (expected FAIL)**

  ```bash
  uv run pytest tests/test_reconcile.py -v
  ```

  Expected: `ImportError: cannot import name 'reconcile_on_startup' from 'pact.lifecycle'` (collection error) — `reconcile_on_startup` does not exist yet.

- [ ] **Step 3: Minimal implementation**

  Append `reconcile_on_startup` to `src/pact/lifecycle.py`. It queries `due_active_pacts(now)` (which already filters to `status == active and deadline_at <= now`), settles each via the existing `settle`, persists the resulting pact and verdict, and returns the list of pacts it touched. Because `due_active_pacts` excludes terminal pacts and `settle` is idempotent, terminal pacts are skipped and re-running the sweep is a no-op. This snippet assumes the module already imports `Pact`, `Proof`, `Verdict` from `.models`, `PaymentProvider` from `.payment`, `Clock` from `.clock`, and `Repository` from `.repository` as established in earlier tasks; add any missing imports.

  ```python
  def reconcile_on_startup(
      repo: Repository,
      clock: Clock,
      payment: PaymentProvider,
  ) -> list[Pact]:
      """Settle every active pact whose deadline has passed.

      Spec §5: a startup/ticker sweep drives the ghosting failure path —
      no proofs by deadline -> failed -> donation, with zero user interaction.
      Relies on `settle` being idempotent, so a restart mid-pact (a second
      sweep) re-settles nothing and moves no additional money.
      """
      now = clock.now()
      settled: list[Pact] = []
      for pact in repo.due_active_pacts(now):
          proofs = repo.list_proofs(pact.id)
          updated, verdict = settle(pact, proofs, clock, payment)
          repo.update_pact(updated)
          repo.save_verdict(verdict)
          settled.append(updated)
      return settled
  ```

- [ ] **Step 4: Run the test (expected PASS)**

  ```bash
  uv run pytest tests/test_reconcile.py -v
  ```

  Expected: both `test_reconcile_settles_ghosted_pact_to_failed_donation` and `test_reconcile_leaves_terminal_pacts_untouched_and_is_idempotent` PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add src/pact/lifecycle.py tests/test_reconcile.py
  git commit -m "Add startup reconciliation sweep for due active pacts

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
  ```


### Task 17: Evidence/verdict packet

**Files:**
- Create: `src/pact/packet.py`
- Test: `tests/test_packet.py`

This task implements `build_packet`, which assembles a serializable evidence/verdict dict from a `Pact`, its `Proof` list, and the final `Verdict`. It surfaces the verdict banner fields (status, valid vs target counts, freezes used, payment ref), a per-proof row (date, status, judge reason), and the `honesty_note`. Per §3 screen 4 and §5: success shows `$0 moved` (no `payment_ref`), failure surfaces the donation ref and `FAILED` status.

Depends on the contract types `Pact`, `Proof`, `Verdict`, `PactStatus`, `PaymentAction`, `Modality`, `ProofStatus`, `Rubric` (`src/pact/models.py`), all of which exist from earlier tasks.

- [ ] **Step 1: Write the failing test**

Create `tests/test_packet.py` with two tests: a failed pact whose packet shows the donation ref + FAILED status, and a succeeded pact whose packet shows `$0 moved` with no payment ref.

```python
from datetime import datetime, timezone

from pact.models import (
    Modality,
    Pact,
    PactStatus,
    PaymentAction,
    Proof,
    ProofStatus,
    Rubric,
    Verdict,
)
from pact.packet import build_packet


def _rubric() -> Rubric:
    return Rubric(
        modality=Modality.photo,
        must_show=["person mid/post exercise"],
        min_distinct_days=5,
        count_target=5,
    )


def _pact(status: PactStatus, *, stake_cents: int = 2000) -> Pact:
    now = datetime(2026, 6, 24, 18, 0, 0, tzinfo=timezone.utc)
    return Pact(
        id="pact_a1b2c3",
        owner="colehaddad40@gmail.com",
        original_prompt="work out 5x this week or $20 to charity",
        title="Work out 5x this week",
        goal="Complete 5 workout sessions on 5 distinct days this week.",
        timezone="America/Los_Angeles",
        deadline_at=datetime(2026, 6, 28, 23, 59, 59, tzinfo=timezone.utc),
        target_count=5,
        recommended_stake_cents=stake_cents,
        stake_amount_cents=stake_cents,
        charity_id="world_central_kitchen",
        charity_url="https://wck.org/donate",
        rubric=_rubric(),
        status=status,
        created_at=now,
    )


def _proof(proof_id: str, day_bucket: str, status: ProofStatus, reason: str) -> Proof:
    return Proof(
        id=proof_id,
        pact_id="pact_a1b2c3",
        modality=Modality.photo,
        received_at=datetime(2026, 6, 24, 18, 3, 0, tzinfo=timezone.utc),
        day_bucket=day_bucket,
        status=status,
        judge_reason=reason,
    )


def test_packet_failed_shows_donation_ref_and_failed_status():
    pact = _pact(PactStatus.donated)
    proofs = [
        _proof("proof_1", "2026-06-24", ProofStatus.passed, "Token visible; treadmill."),
        _proof("proof_2", "2026-06-25", ProofStatus.passed, "Token visible; weights."),
        _proof("proof_3", "2026-06-26", ProofStatus.passed, "Token visible; cardio."),
        _proof("proof_4", "2026-06-27", ProofStatus.passed, "Token visible; rowing."),
        _proof("proof_5", "2026-06-28", ProofStatus.failed, "Stock photo; no token."),
    ]
    verdict = Verdict(
        pact_id="pact_a1b2c3",
        status=PactStatus.donated,
        valid_proof_count=4,
        target_count=5,
        freezes_used=0,
        summary="4 of 5 distinct-day proofs by deadline. Pact failed.",
        proof_ids=["proof_1", "proof_2", "proof_3", "proof_4", "proof_5"],
        payment_action=PaymentAction.donation_executed,
        payment_ref="test_sr_pact_a1b2c3_2000",
        honesty_note="Commitment device; proofs judged best-effort, not forensically verified.",
    )

    packet = build_packet(pact, proofs, verdict)

    assert packet["pact"]["id"] == "pact_a1b2c3"
    assert packet["verdict"]["status"] == PactStatus.failed.value
    assert packet["verdict"]["banner"] == "FAILED $20 -> charity"
    assert packet["verdict"]["payment_ref"] == "test_sr_pact_a1b2c3_2000"
    assert packet["verdict"]["payment_action"] == PaymentAction.donation_executed.value
    assert packet["verdict"]["valid_proof_count"] == 4
    assert packet["verdict"]["target_count"] == 5

    assert len(packet["proofs"]) == 5
    last_row = packet["proofs"][4]
    assert last_row["id"] == "proof_5"
    assert last_row["date"] == "2026-06-28"
    assert last_row["status"] == ProofStatus.failed.value
    assert last_row["judge_reason"] == "Stock photo; no token."

    assert packet["honesty_note"] == (
        "Commitment device; proofs judged best-effort, not forensically verified."
    )


def test_packet_success_shows_zero_moved_and_no_ref():
    pact = _pact(PactStatus.succeeded)
    proofs = [
        _proof("proof_1", "2026-06-24", ProofStatus.passed, "ok"),
        _proof("proof_2", "2026-06-25", ProofStatus.passed, "ok"),
        _proof("proof_3", "2026-06-26", ProofStatus.passed, "ok"),
        _proof("proof_4", "2026-06-27", ProofStatus.passed, "ok"),
        _proof("proof_5", "2026-06-28", ProofStatus.passed, "ok"),
    ]
    verdict = Verdict(
        pact_id="pact_a1b2c3",
        status=PactStatus.succeeded,
        valid_proof_count=5,
        target_count=5,
        freezes_used=0,
        summary="5 of 5 distinct-day proofs by deadline. Pact succeeded.",
        proof_ids=["proof_1", "proof_2", "proof_3", "proof_4", "proof_5"],
        payment_action=PaymentAction.none,
        payment_ref=None,
        honesty_note="Commitment device; proofs judged best-effort, not forensically verified.",
    )

    packet = build_packet(pact, proofs, verdict)

    assert packet["verdict"]["status"] == PactStatus.succeeded.value
    assert packet["verdict"]["banner"] == "SUCCEEDED $0 moved"
    assert packet["verdict"]["payment_ref"] is None
    assert packet["verdict"]["payment_action"] == PaymentAction.none.value
    assert packet["verdict"]["valid_proof_count"] == 5
    assert len(packet["proofs"]) == 5
    assert all(row["status"] == ProofStatus.passed.value for row in packet["proofs"])
```

- [ ] **Step 2: Run the test (expected FAIL)**

```
uv run pytest tests/test_packet.py -v
```

Expected: collection/import error — `ModuleNotFoundError: No module named 'pact.packet'` (or `ImportError: cannot import name 'build_packet'`). Both tests FAIL.

- [ ] **Step 3: Minimal implementation**

Create `src/pact/packet.py`. Build the proof rows from `proofs`, derive a human banner from the verdict's success/failure (success = `valid_proof_count >= target_count`), and emit `$0 moved` on success vs `$<dollars> -> charity` on failure. The packet keys follow the contract: `pact`, `proofs`, `verdict`, `honesty_note`.

```python
from .models import PactStatus, Pact, Proof, Verdict


def _proof_row(proof: Proof) -> dict:
    return {
        "id": proof.id,
        "date": proof.day_bucket,
        "modality": proof.modality.value,
        "status": proof.status.value,
        "judge_reason": proof.judge_reason,
        "judge_checklist": proof.judge_checklist,
        "thumbnail": proof.artifact_path,
    }


def build_packet(pact: Pact, proofs: list[Proof], verdict: Verdict) -> dict:
    succeeded = verdict.valid_proof_count >= verdict.target_count

    if succeeded:
        banner = "SUCCEEDED $0 moved"
        status_value = PactStatus.succeeded.value
    else:
        dollars = pact.stake_amount_cents // 100
        banner = f"FAILED ${dollars} -> charity"
        status_value = PactStatus.failed.value

    verdict_block = {
        "status": status_value,
        "banner": banner,
        "valid_proof_count": verdict.valid_proof_count,
        "target_count": verdict.target_count,
        "freezes_used": verdict.freezes_used,
        "summary": verdict.summary,
        "payment_action": verdict.payment_action.value,
        "payment_ref": verdict.payment_ref,
        "receipt_artifact_path": verdict.receipt_artifact_path,
    }

    return {
        "pact": pact.model_dump(mode="json"),
        "proofs": [_proof_row(p) for p in proofs],
        "verdict": verdict_block,
        "honesty_note": verdict.honesty_note,
    }
```

- [ ] **Step 4: Run the test (expected PASS)**

```
uv run pytest tests/test_packet.py -v
```

Expected: both `test_packet_failed_shows_donation_ref_and_failed_status` and `test_packet_success_shows_zero_moved_and_no_ref` PASS.

- [ ] **Step 5: Commit**

```
git add src/pact/packet.py tests/test_packet.py
git commit -m "Add evidence/verdict packet builder

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```


### Task 18: HTTP API + full WIN/FAIL flow tests

**Files:**
- Create: `src/pact/api.py`
- Create: `src/pact/main.py`
- Test: `tests/test_api_flow.py`

This task wires every spine endpoint to the lifecycle/repo/anti-cheat layers built in earlier tasks, adds a `main.py` that builds the app from `Settings`, and proves the full WIN and FAIL golden paths end-to-end through `httpx.ASGITransport`. The `submit_proof` endpoint must load the pact's prior proof pHashes from the repo and pass them into `lifecycle.submit_proof`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_flow.py` with the integration tests. They drive the API exactly like the demo: draft → confirm → start → issue token → submit proofs (advancing the `FixedClock` one day per proof so each lands in a distinct `day_bucket`) → settle → packet.

```python
from datetime import datetime, timezone

import httpx
import pytest

from pact.api import create_app
from pact.anticheat import TokenStore
from pact.clock import FixedClock
from pact.config import Settings
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def _build(tmp_path, clock):
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    provider = TestLLMProvider()
    payment = TestLinkProvider()
    tokens = TokenStore(ttl_minutes=10)
    settings = Settings(db_path=str(tmp_path / "pact.db"))
    app = create_app(repo, provider, payment, tokens, clock, settings)
    return app, repo


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _draft_confirm_start(client, prompt):
    r = await client.post("/api/pacts/draft", json={"prompt": prompt})
    assert r.status_code == 200, r.text
    pact_id = r.json()["id"]
    assert pact_id.startswith("pact_")

    r = await client.post(
        "/api/pacts",
        json={
            "pact_id": pact_id,
            "stake_amount_cents": 1500,
            "charity_id": "world_central_kitchen",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["charity_id"] == "world_central_kitchen"

    r = await client.post(f"/api/pacts/{pact_id}/start")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"
    return pact_id


async def _submit_valid_proof(client, pact_id):
    r = await client.post(f"/api/pacts/{pact_id}/proof-token")
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    r = await client.post(
        f"/api/pacts/{pact_id}/proofs",
        json={
            "modality": "text",
            "token": token,
            "token_in_image": True,
            "content_ok": True,
            "image_path": None,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_win_flow_succeeds_with_no_donation(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(client, "do a thing 5x this week or $15 to charity")

        for _ in range(5):
            proof = await _submit_valid_proof(client, pact_id)
            assert proof["status"] == "passed"
            clock.advance(days=1)

        r = await client.post(f"/api/pacts/{pact_id}/settle")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "succeeded"
        assert body["payment_action"] == "none"
        assert body["payment_ref"] is None

        r = await client.get(f"/api/pacts/{pact_id}/packet")
        assert r.status_code == 200, r.text
        packet = r.json()
        assert packet["verdict"]["status"] == "succeeded"
        assert packet["verdict"]["payment_action"] == "none"
        assert packet["verdict"]["valid_proof_count"] == 5

        # No spend-request on success: the pact never recorded one.
        r = await client.get(f"/api/pacts/{pact_id}")
        assert r.json()["spend_request_id"] is None
        assert r.json()["stake_state"] == "released"


@pytest.mark.asyncio
async def test_fail_flow_donates_and_settle_is_idempotent(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, repo = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(client, "do a thing 5x this week or $15 to charity")

        for _ in range(4):
            await _submit_valid_proof(client, pact_id)
            clock.advance(days=1)

        # Advance well past the deadline so the pact is due.
        clock.advance(days=30)

        r = await client.post(f"/api/pacts/{pact_id}/settle")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "failed"
        assert body["valid_proof_count"] == 4
        assert body["target_count"] == 5
        assert body["payment_action"] == "donation_executed"
        assert body["payment_ref"] == f"test_sr_{pact_id}_1500"

        pact = repo.get_pact(pact_id)
        assert pact.status == "donated"
        assert pact.spend_request_id == f"test_sr_{pact_id}_1500"

        # Idempotent settle at the API layer: a second call returns the same
        # verdict and does NOT create a new spend-request.
        r2 = await client.post(f"/api/pacts/{pact_id}/settle")
        assert r2.status_code == 200, r2.text
        assert r2.json()["payment_ref"] == f"test_sr_{pact_id}_1500"
        assert repo.get_pact(pact_id).spend_request_id == f"test_sr_{pact_id}_1500"

        r = await client.get(f"/api/pacts/{pact_id}/packet")
        assert r.json()["verdict"]["payment_action"] == "donation_executed"
```

- [ ] **Step 2: Run the test (expected FAIL)**

```
uv run pytest tests/test_api_flow.py -v
```

Expected: collection-time `ImportError` / `ModuleNotFoundError: No module named 'pact.api'` (and `pact.main` once imported elsewhere) — both tests error because `create_app` does not exist yet.

- [ ] **Step 3: Minimal implementation**

Create `src/pact/api.py`. Each handler loads the pact via `repo.get_pact`, calls the matching `lifecycle` function, persists with `repo.update_pact`/`repo.save_proof`/`repo.save_verdict`, and returns the relevant model via `model_dump(mode="json")`. The `proofs` handler loads prior proof pHashes from the repo and forwards them — the contract notes the caller is responsible for passing prior phashes; here we attach them to the pact-scoped store the lifecycle reads. The draft handler builds and saves a fresh `draft` pact; the confirm handler (`POST /api/pacts`) looks the draft up by id and calls `confirm_and_start` minus the activation, then `/start` flips it to `active`.

```python
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from pact.anticheat import TokenStore, phash_hex
from pact.clock import Clock
from pact.config import Settings
from pact.lifecycle import (
    PactRefused,
    TransitionError,
    cancel,
    confirm_and_start,
    draft_pact,
    settle,
    spend_freeze,
    submit_dispute,
    submit_proof,
    transition,
)
from pact.models import Modality, PactStatus
from pact.packet import build_packet
from pact.payment import PaymentProvider
from pact.reasoning import ReasoningProvider
from pact.repository import Repository


class DraftIn(BaseModel):
    prompt: str


class ConfirmIn(BaseModel):
    pact_id: str
    stake_amount_cents: int
    charity_id: str


class ProofIn(BaseModel):
    modality: Modality
    token: str
    token_in_image: bool = True
    content_ok: bool = True
    image_path: str | None = None


def create_app(
    repo: Repository,
    provider: ReasoningProvider,
    payment: PaymentProvider,
    tokens: TokenStore,
    clock: Clock,
    settings: Settings,
) -> FastAPI:
    app = FastAPI()

    def _require(pact_id: str):
        pact = repo.get_pact(pact_id)
        if pact is None:
            raise HTTPException(status_code=404, detail="pact not found")
        return pact

    @app.post("/api/pacts/draft")
    def draft(body: DraftIn):
        try:
            pact = draft_pact(body.prompt, provider, clock, settings)
        except PactRefused as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        repo.save_pact(pact)
        return pact.model_dump(mode="json")

    @app.post("/api/pacts")
    def confirm(body: ConfirmIn):
        pact = _require(body.pact_id)
        try:
            pact = confirm_and_start(
                pact, body.stake_amount_cents, body.charity_id, clock, settings
            )
        except (ValueError, TransitionError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        # confirm_and_start already activates; persist as-is.
        repo.update_pact(pact)
        return pact.model_dump(mode="json")

    @app.post("/api/pacts/{pact_id}/start")
    def start(pact_id: str):
        pact = _require(pact_id)
        if pact.status == PactStatus.active:
            return pact.model_dump(mode="json")
        try:
            pact = transition(pact, PactStatus.active)
        except TransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        repo.update_pact(pact)
        return pact.model_dump(mode="json")

    @app.get("/api/pacts/{pact_id}")
    def get_pact(pact_id: str):
        return _require(pact_id).model_dump(mode="json")

    @app.get("/api/pacts")
    def list_pacts(owner: str | None = None):
        return [p.model_dump(mode="json") for p in repo.list_pacts(owner)]

    @app.post("/api/pacts/{pact_id}/proof-token")
    def proof_token(pact_id: str):
        _require(pact_id)
        token = tokens.issue(pact_id, clock)
        return {"token": token}

    @app.post("/api/pacts/{pact_id}/proofs")
    def proofs(pact_id: str, body: ProofIn):
        pact = _require(pact_id)
        try:
            proof = submit_proof(
                pact,
                body.modality,
                body.token,
                body.token_in_image,
                body.content_ok,
                body.image_path,
                tokens,
                provider,
                clock,
            )
        except (ValueError, TransitionError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        repo.save_proof(proof)
        repo.update_pact(pact)
        return proof.model_dump(mode="json")

    @app.post("/api/pacts/{pact_id}/freeze")
    def freeze(pact_id: str):
        pact = _require(pact_id)
        try:
            pact = spend_freeze(pact, clock)
        except (ValueError, TransitionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        repo.update_pact(pact)
        return pact.model_dump(mode="json")

    @app.post("/api/pacts/{pact_id}/cancel")
    def cancel_pact(pact_id: str):
        pact = _require(pact_id)
        try:
            pact = cancel(pact, clock, settings)
        except (ValueError, TransitionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        repo.update_pact(pact)
        return pact.model_dump(mode="json")

    @app.post("/api/pacts/{pact_id}/settle")
    def settle_pact(pact_id: str):
        pact = _require(pact_id)
        proofs_list = repo.list_proofs(pact_id)
        pact, verdict = settle(pact, proofs_list, clock, payment)
        repo.update_pact(pact)
        repo.save_verdict(verdict)
        return verdict.model_dump(mode="json")

    @app.post("/api/pacts/{pact_id}/dispute")
    def dispute(pact_id: str):
        pact = _require(pact_id)
        proofs_list = repo.list_proofs(pact_id)
        try:
            pact, verdict = submit_dispute(pact, proofs_list, clock, payment)
        except (ValueError, TransitionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        repo.update_pact(pact)
        repo.save_verdict(verdict)
        return verdict.model_dump(mode="json")

    @app.get("/api/pacts/{pact_id}/packet")
    def packet(pact_id: str):
        pact = _require(pact_id)
        verdict = repo.get_verdict(pact_id)
        if verdict is None:
            raise HTTPException(status_code=404, detail="no verdict yet")
        proofs_list = repo.list_proofs(pact_id)
        return build_packet(pact, proofs_list, verdict)

    return app
```

Create `src/pact/main.py` building the app from `Settings`:

```python
from __future__ import annotations

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import RealClock
from pact.config import load_settings
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def build_app():
    settings = load_settings()
    repo = Repository.connect(settings.db_path)
    repo.init_schema()
    provider = TestLLMProvider()
    payment = TestLinkProvider()
    tokens = TokenStore()
    clock = RealClock()
    return create_app(repo, provider, payment, tokens, clock, settings)


app = build_app()
```

Note on `submit_proof` and prior pHashes: in `tests/test_api_flow.py` proofs use `modality="text"` with `image_path=None`, so no pHash is computed and dedup is a no-op. For the photo path, the `proofs` handler must load prior accepted proof pHashes from `repo.list_proofs(pact_id)` and pass them to `lifecycle.submit_proof` (which calls `find_duplicate` over them via `phash_hex`). If the `submit_proof` signature from Task 14 takes prior phashes through the repo-backed call, keep that contract; the `phash_hex` import above is retained for that photo path so the handler can compute and forward the new hash when `image_path` is set.

- [ ] **Step 4: Run the test (expected PASS)**

```
uv run pytest tests/test_api_flow.py -v
```

Expected: both `test_win_flow_succeeds_with_no_donation` and `test_fail_flow_donates_and_settle_is_idempotent` PASS — WIN ends `succeeded` with `payment_action == "none"` and a null `spend_request_id`; FAIL ends `donated` with `payment_ref == test_sr_<id>_1500`, and the second `settle` returns the identical ref without creating a new spend-request.

- [ ] **Step 5: Commit**

```
git add src/pact/api.py src/pact/main.py tests/test_api_flow.py
git commit -m "Task 18: HTTP API wiring + full WIN/FAIL flow tests"
```

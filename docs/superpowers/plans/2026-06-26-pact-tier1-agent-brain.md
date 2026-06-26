# Pact Tier-1 — Wire the Agent-as-Brain + Autonomous Settle

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the running app actually use the broker/agent reasoning path (config-driven, not hardcoded to the `test_llm` stub) and settle deadlines autonomously, so "the Hermes agent is the brain" and the failure→donation arc are real in production — not just the demo clock.

**Locked decision honored:** the brain is a Hermes AGENT, not a backend model call. No LLM client is added to the backend; real reasoning comes from a Hermes agent running the `/pact` skill or the HTTP worker, with `TestLLMProvider` as the deterministic fallback. No real money/network in tests.

**Scope:** config knobs; fix `BrokerReasoningProvider` to enqueue→poll→fallback (+`agent_only`); a provider/payment factory wired into `main.py`; an HTTP `pact serve` worker + CLI so a real agent can claim the live server's queue; a FastAPI lifespan that runs startup reconciliation + a background scheduler ticker on the real clock.

**Tech:** Python 3.11+, uv, FastAPI, Pydantic v2, SQLite, pytest + httpx (async). Builds on master (254 tests).

**Spec:** [`docs/superpowers/specs/2026-06-24-pact-design.md`](../specs/2026-06-24-pact-design.md) §3.

**Order:** Task 1 (config) → 2 (provider) → 3 (factory/main) → 4 (http worker) → 5 (cli/relay) → 6 (lifespan). Tasks 3 and 6 touch main.py.

---

## Tasks


### Task 1: Config: timeout + scheduler knobs

**Files:**
- Modify: `src/pact/config.py`
- Test (Create): `tests/test_config_tier1.py`

Add three frozen `Settings` fields and their `load_settings` env wiring:
- `reasoning_timeout_polls: int = 0` ← `PACT_REASONING_TIMEOUT_POLLS`
- `scheduler_enabled: bool = True` ← `PACT_SCHEDULER_ENABLED`
- `scheduler_interval_seconds: int = 60` ← `PACT_SCHEDULER_INTERVAL_SECONDS`

The int fields reuse the existing `_int` helper. The bool field needs a new `_bool` helper that accepts the usual truthy/falsy spellings. All existing config tests (`tests/test_config.py`, `tests/test_config_day2.py`) MUST still pass unchanged — these are pure additive fields with defaults.

---

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_tier1.py` with the complete contents below.

```python
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
```

- [ ] **Step 2: Run the test (expect FAIL)**

```
uv run pytest tests/test_config_tier1.py -v
```

Expected: collection succeeds but tests FAIL with `TypeError: Settings.__init__() got an unexpected keyword argument 'reasoning_timeout_polls'` / `AttributeError: 'Settings' object has no attribute 'reasoning_timeout_polls'` (and the `scheduler_enabled` / `scheduler_interval_seconds` assertions error the same way), because the new fields and the `_bool` helper do not exist yet.

- [ ] **Step 3: Minimal implementation**

Replace the entire contents of `src/pact/config.py` with the version below. This adds the three fields to the frozen dataclass, adds the `_bool` helper next to `_int`/`_str`, and wires the three env keys in `load_settings`. Everything else is byte-for-byte the existing file.

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
        link_mode=_str(env, "PACT_LINK_MODE", "dry_run"),
        reasoning_timeout_polls=_int(env, "PACT_REASONING_TIMEOUT_POLLS", 0),
        scheduler_enabled=_bool(env, "PACT_SCHEDULER_ENABLED", True),
        scheduler_interval_seconds=_int(env, "PACT_SCHEDULER_INTERVAL_SECONDS", 60),
    )
```

Notes:
- `_bool` treats both a missing key and an empty/whitespace-only value as "no override" → returns the default. This matches `test_scheduler_enabled_blank_keeps_default_true` and mirrors how the existing int helper distinguishes "absent" from "present but invalid" (a non-empty unrecognized value raises).
- The new fields are appended at the end of the dataclass so positional construction elsewhere is unaffected, and they are purely additive with defaults, so `tests/test_config.py` and `tests/test_config_day2.py` remain green.

- [ ] **Step 4: Run the test (expect PASS) + confirm no config regressions**

```
uv run pytest tests/test_config_tier1.py tests/test_config.py tests/test_config_day2.py -v
```

Expected: all tests in `tests/test_config_tier1.py` PASS, and the existing `tests/test_config.py` and `tests/test_config_day2.py` remain PASS (no regressions). Optionally run the full suite to confirm the additive fields broke nothing elsewhere:

```
uv run pytest -q
```

Expected: the previously-passing 254 tests still pass, plus the new `tests/test_config_tier1.py` cases.

- [ ] **Step 5: Commit**

```
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' add src/pact/config.py tests/test_config_tier1.py
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' commit -m "$(cat <<'EOF'
feat(config): add Tier-1 reasoning-timeout + scheduler knobs

Add reasoning_timeout_polls (PACT_REASONING_TIMEOUT_POLLS),
scheduler_enabled (PACT_SCHEDULER_ENABLED), and
scheduler_interval_seconds (PACT_SCHEDULER_INTERVAL_SECONDS) to
Settings + load_settings, with a new _bool env helper. Additive,
defaults preserve existing behavior.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

No existing call sites change: `Settings()` and `load_settings(...)` keep their signatures (the additions are keyword fields with defaults), so `main.build_app()`, `factory.py` (Task 3), and all current callers compile unchanged.


### Task 2: BrokerReasoningProvider: enqueue + poll + fallback + agent_only

Refactor `BrokerReasoningProvider` so that `resolve` actually **enqueues** the task into the broker (so a connected worker can claim it), **polls** `broker.get_result` up to `timeout_polls` times (sleeping via an injected, no-op-in-tests `sleep`), returns the agent-posted result if one appears, and otherwise either falls back to the deterministic stub (`allow_fallback=True`) or raises `ReasoningUnavailable` (`allow_fallback=False`). `capabilities()` keeps delegating to the fallback.

The current code (`src/pact/reasoning.py` lines 245–288) only *reads* `repo.get_task` and never enqueues — so a worker never sees website tasks. This task fixes that bug while keeping every existing `tests/test_broker_provider.py` assertion green.

**Files:**
- Modify: `src/pact/reasoning.py` (add `class ReasoningUnavailable(Exception)`; rewrite `BrokerReasoningProvider.__init__` and `resolve`; keep `capabilities`)
- Test (new): `tests/test_broker_provider_tier1.py`
- Test (keep green, no edits required): `tests/test_broker_provider.py`

**Key signatures already confirmed from source (do not change them):**
- `make_reasoning_task(type, pact_id, input, clock, required_capability=None) -> ReasoningTask` — id is `"task_" + sha1(f"{type.value}:{pact_id}:{now.isoformat()}:{sorted(input.items())!r}")[:8]`, so the same `(type, pact_id, input, required_capability, clock.now())` always yields the same id (equivalence is id-based).
- `broker.enqueue(repo, type, pact_id, input, clock, required_capability=None) -> ReasoningTask` — builds via `make_reasoning_task` then `repo.save_task` (which is `INSERT OR REPLACE` by id). **Important:** because `enqueue` would overwrite an existing done task back to `pending`, `resolve` must NOT blindly re-enqueue when a task with the same id already exists. Enqueue only when `repo.get_task(id)` is `None`.
- `broker.get_result(repo, task_id) -> dict | None` — returns the result only when status is `done`, else `None`.
- `TestLLMProvider().capabilities() == {"text", "vision"}`; its `_judge_proof` returns `{"status": "passed", ...}` when `token_ok and not is_duplicate and content_ok`, and `{"status": "failed", "reason": "Required nonce token not verified; rejecting proof.", ...}` when `token_ok` is False.

---

- [ ] **Step 1: Write the failing test**

Create `tests/test_broker_provider_tier1.py` with the full content below. These assertions exercise the new contract: enqueue-on-resolve, agent-result-wins, and the `allow_fallback=False` raise path. A no-op `sleep` is injected so the poll loop never actually sleeps; a list captures the per-poll sleep intervals so we can assert determinism (zero sleeps at `timeout_polls=0`).

```python
from datetime import datetime, timezone

import pytest

from pact import broker
from pact.clock import FixedClock
from pact.models import TaskStatus, TaskType
from pact.reasoning import (
    BrokerReasoningProvider,
    ReasoningUnavailable,
    TestLLMProvider,
    make_reasoning_task,
)
from pact.repository import Repository


@pytest.fixture()
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 6, 25, 12, 0, 0, tzinfo=timezone.utc))


@pytest.fixture()
def repo(tmp_path) -> Repository:
    r = Repository.connect(str(tmp_path / "broker_provider_tier1.db"))
    r.init_schema()
    yield r
    r.close()


def _noop_sleep_recorder():
    """Return (sleep_fn, calls) where calls records every interval slept."""
    calls: list[float] = []

    def sleep(seconds: float) -> None:
        calls.append(seconds)

    return sleep, calls


def test_no_worker_with_fallback_returns_stub_and_enqueues_task(repo, clock):
    """No worker connected + allow_fallback=True:
    - resolve returns the deterministic stub result, AND
    - the task is now visible in the broker as a pending task (it was enqueued).
    """
    sleep, sleep_calls = _noop_sleep_recorder()
    fallback = TestLLMProvider()
    provider = BrokerReasoningProvider(
        repo,
        clock,
        fallback,
        timeout_polls=0,
        sleep=sleep,
        allow_fallback=True,
    )
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_enq",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        clock,
    )

    # Before resolve, the broker has no such task.
    assert repo.get_task(task.id) is None

    result = provider.resolve(task)

    # Fallback (TestLLMProvider) result, deterministic.
    assert result["status"] == "passed"
    assert result["checklist"] == {"token": True, "content": True, "not_dup": True}

    # The task was enqueued so a worker could have claimed it.
    stored = repo.get_task(task.id)
    assert stored is not None
    assert stored.status == TaskStatus.pending
    assert stored.id in {t.id for t in broker.pending_for(repo)}

    # timeout_polls=0 => no polling, so no sleeps at all (fully deterministic).
    assert sleep_calls == []


def test_pre_posted_agent_result_wins_over_fallback(repo, clock):
    """A matching result already posted by an agent is returned verbatim,
    and the fallback is never consulted."""
    sleep, sleep_calls = _noop_sleep_recorder()
    fallback = TestLLMProvider()
    provider = BrokerReasoningProvider(
        repo,
        clock,
        fallback,
        timeout_polls=3,
        sleep=sleep,
        allow_fallback=True,
    )
    # Enqueue the EQUIVALENT task, then mark it done with an agent result that
    # deliberately differs from what the fallback would produce.
    enq = broker.enqueue(
        repo,
        TaskType.judge_proof,
        "pact_agent",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        clock,
    )
    enq.status = TaskStatus.done
    agent_result = {"status": "passed", "reason": "agent reviewed", "checklist": {}}
    enq.result = agent_result
    repo.update_task(enq)

    incoming = make_reasoning_task(
        TaskType.judge_proof,
        "pact_agent",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        clock,
    )
    assert incoming.id == enq.id  # equivalence is id-based

    result = provider.resolve(incoming)

    assert result == agent_result
    assert result["reason"] == "agent reviewed"  # not the fallback's reason
    # Result was available on the first poll, so no sleeps happened.
    assert sleep_calls == []


def test_agent_only_no_result_raises_reasoning_unavailable(repo, clock):
    """allow_fallback=False + no agent result => ReasoningUnavailable,
    and the loop polled+slept exactly timeout_polls times before giving up."""
    sleep, sleep_calls = _noop_sleep_recorder()
    fallback = TestLLMProvider()
    provider = BrokerReasoningProvider(
        repo,
        clock,
        fallback,
        timeout_polls=2,
        sleep=sleep,
        allow_fallback=False,
    )
    task = make_reasoning_task(
        TaskType.judge_proof,
        "pact_only",
        {"token_ok": True, "is_duplicate": False, "content_ok": True},
        clock,
    )

    with pytest.raises(ReasoningUnavailable):
        provider.resolve(task)

    # Task was still enqueued so a worker could (later) pick it up.
    stored = repo.get_task(task.id)
    assert stored is not None
    assert stored.status == TaskStatus.pending

    # Polled timeout_polls times with a sleep between each poll attempt.
    assert len(sleep_calls) == 2


def test_capabilities_still_delegate_to_fallback(repo, clock):
    fallback = TestLLMProvider()
    provider = BrokerReasoningProvider(
        repo, clock, fallback, timeout_polls=0, allow_fallback=False
    )
    assert provider.capabilities() == {"text", "vision"}
```

- [ ] **Step 2: Run the new test — expect FAIL**

```bash
uv run pytest tests/test_broker_provider_tier1.py -v
```

Expected: FAIL — `ImportError: cannot import name 'ReasoningUnavailable' from 'pact.reasoning'` (the exception does not exist yet), and even after that the `__init__` does not accept `sleep`/`allow_fallback` and `resolve` neither enqueues nor raises.

- [ ] **Step 3: Minimal implementation**

In `src/pact/reasoning.py`:

(a) Add the stdlib import and a default interval at the top of the module. Change the existing import line:

```python
import hashlib
from typing import Protocol
```

to:

```python
import hashlib
import time
from typing import Protocol
```

(b) Add the broker dependency import near the top of the file (after the existing `from .models import ...` line). Place it inside the function instead of at module top to avoid a circular import (`broker` imports `make_reasoning_task` from this module), so do NOT add a module-level `import`. Instead, import lazily inside `resolve` (shown below).

(c) Add the new exception just above the `BrokerReasoningProvider` class definition:

```python
class ReasoningUnavailable(Exception):
    """Raised when agent reasoning is required (no fallback allowed) but no
    worker posted a result before the poll budget was exhausted."""
```

(d) Replace the entire `BrokerReasoningProvider` class (current lines 245–288) with:

```python
class BrokerReasoningProvider:
    """Hybrid provider: enqueue the task so a connected worker can claim it,
    poll the broker for an agent-posted result up to ``timeout_polls`` times,
    and either return that result, fall back to the deterministic stub
    (``allow_fallback=True``), or raise :class:`ReasoningUnavailable`
    (``allow_fallback=False``).

    Equivalence is by deterministic task id: two tasks with the same
    (type, pact_id, sorted(input), required_capability, clock.now()) map to the
    same id via ``make_reasoning_task``. The task is enqueued only when no task
    with that id already exists, so an already-posted ``done`` result is never
    overwritten back to ``pending``.

    ``sleep`` is injected (defaults to ``time.sleep``) so tests pass a no-op and
    stay deterministic; ``timeout_polls=0`` means "no agent connected -> enqueue
    then immediately fall back / raise" with no sleeping.
    """

    def __init__(
        self,
        repo,
        clock,
        fallback: "ReasoningProvider",
        timeout_polls: int = 0,
        sleep=time.sleep,
        allow_fallback: bool = True,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self.repo = repo
        self.clock = clock
        self.fallback = fallback
        self.timeout_polls = timeout_polls
        self.sleep = sleep
        self.allow_fallback = allow_fallback
        self.poll_interval_seconds = poll_interval_seconds

    def capabilities(self) -> set[str]:
        return self.fallback.capabilities()

    def resolve(self, task: ReasoningTask) -> dict:
        from . import broker  # lazy import to avoid a circular import

        equivalent = make_reasoning_task(
            task.type,
            task.pact_id,
            task.input,
            self.clock,
            task.required_capability,
        )
        # Enqueue so a connected worker can claim+resolve it -- but only if it
        # is not already in the broker (avoid clobbering an in-flight/done task).
        existing = self.repo.get_task(equivalent.id)
        if existing is None:
            broker.enqueue(
                self.repo,
                task.type,
                task.pact_id,
                task.input,
                self.clock,
                required_capability=task.required_capability,
            )

        # Poll for an agent-posted result. A result already present is found on
        # the first read; otherwise sleep between attempts.
        result = broker.get_result(self.repo, equivalent.id)
        for _ in range(self.timeout_polls):
            if result is not None:
                return result
            self.sleep(self.poll_interval_seconds)
            result = broker.get_result(self.repo, equivalent.id)
        if result is not None:
            return result

        if self.allow_fallback:
            return self.fallback.resolve(task)
        raise ReasoningUnavailable(
            f"no agent result for task {equivalent.id} after "
            f"{self.timeout_polls} polls and fallback is disabled"
        )
```

Note on the loop semantics that the new tests rely on:
- The pre-posted-result test uses `timeout_polls=3` but the result is present on the very first `broker.get_result`, so the `for` loop's first iteration returns immediately and `sleep` is never called (`sleep_calls == []`).
- The `agent_only` test uses `timeout_polls=2` with no result, so the loop sleeps once per iteration (2 sleeps) and then raises — matching `len(sleep_calls) == 2`.
- The no-worker fallback test uses `timeout_polls=0`, so the `for` loop body never runs, `result` stays `None`, and it falls straight through to `self.fallback.resolve(task)` with zero sleeps.

- [ ] **Step 4: Run the new test — expect PASS**

```bash
uv run pytest tests/test_broker_provider_tier1.py -v
```

Expected: PASS — all four tests green.

- [ ] **Step 5: Run the existing broker-provider test to confirm no regression**

The existing `tests/test_broker_provider.py` constructs the provider positionally as `BrokerReasoningProvider(repo, clock, fallback)` and `BrokerReasoningProvider(repo, clock, fallback, timeout_polls=N)` — both remain valid because `sleep`, `allow_fallback`, and `poll_interval_seconds` are new keyword args with defaults. Its `test_pre_posted_result_is_returned_over_fallback` pre-creates the done task with the same id, so the new `existing is None` guard skips re-enqueue and the agent result is returned. `test_pre_posted_not_done_falls_back` enqueues a still-pending task, finds no result, and falls back (`allow_fallback` defaults to True). `test_no_worker_*` enqueue-then-fallback with `timeout_polls=0` and the default `time.sleep` (never invoked).

```bash
uv run pytest tests/test_broker_provider.py tests/test_broker_provider_tier1.py -v
```

Expected: PASS — all existing tests plus the four new ones.

- [ ] **Step 6: Run the full suite to confirm the 254 baseline still passes**

```bash
uv run pytest -q
```

Expected: PASS — previously-passing tests unchanged, plus the 4 new tests (258 total).

- [ ] **Step 7: Commit**

```bash
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' add src/pact/reasoning.py tests/test_broker_provider_tier1.py
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' commit -m "fix(reasoning): BrokerReasoningProvider enqueues + polls + fallback/agent_only

resolve() now enqueues the task into the broker so a connected worker can
claim it (was a read-only bug: workers never saw website tasks), polls
broker.get_result up to timeout_polls with an injected sleep, returns the
agent result if posted, else falls back (allow_fallback=True) or raises
ReasoningUnavailable (allow_fallback=False). Enqueue is id-guarded so an
already-done result is never overwritten back to pending.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

**Call sites to update:** none. The signature change is purely additive — `sleep`, `allow_fallback`, and `poll_interval_seconds` are new keyword args with defaults, so the only current caller pattern (`BrokerReasoningProvider(repo, clock, fallback[, timeout_polls=...])` in `tests/test_broker_provider.py`) keeps working unchanged. The config-driven construction in `src/pact/factory.py` (Task 3) will pass `timeout_polls`, `allow_fallback`, and `fallback` explicitly.


### Task 3: Provider/payment factory + main wiring

**Files:**
- Create: `src/pact/factory.py`
- Modify: `src/pact/main.py`
- Test: `tests/test_factory.py`

This task introduces `src/pact/factory.py` with two config-driven selectors and rewires `main.build_app()` to call them instead of hardcoding `TestLLMProvider()` / `TestLinkProvider()`. It assumes the earlier Tier-1 tasks already landed:
- `config.Settings` has the new field `reasoning_timeout_polls: int = 0` (env `PACT_REASONING_TIMEOUT_POLLS`).
- `reasoning.BrokerReasoningProvider.__init__(self, repo, clock, fallback, timeout_polls=0, sleep=time.sleep, allow_fallback=True)` and `reasoning.ReasoningUnavailable` exist.

If those are not yet present, this task's `agent_only`/`hybrid` assertions on `allow_fallback` will fail; land the config + reasoning tasks first. The factory itself only depends on the constructor accepting `timeout_polls=` and `allow_fallback=` keyword args.

---

- [ ] **Step 1: Write the failing test**

Create `tests/test_factory.py`. It covers: each `reasoning_mode` returns the right provider type (with the right `allow_fallback`/`timeout_polls` for the broker modes), `payment_mode` selects `TestLinkProvider` vs `LinkCliProvider` (delegating to `get_payment_provider`), and `main.build_app()` still returns a FastAPI app (smoke). Tests are deterministic — no sleep, no network, no DB file leakage (the broker modes use the in-memory-style on-disk repo fixture; `build_app` smoke runs against a `tmp_path` DB via env).

```python
import os
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI

from pact import factory
from pact.clock import FixedClock
from pact.config import Settings, load_settings
from pact.payment import LinkCliProvider, PaymentProvider, TestLinkProvider
from pact.reasoning import (
    BrokerReasoningProvider,
    ReasoningProvider,
    TestLLMProvider,
)
from pact.repository import Repository


@pytest.fixture()
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 6, 25, 12, 0, 0, tzinfo=timezone.utc))


@pytest.fixture()
def repo(tmp_path) -> Repository:
    r = Repository.connect(str(tmp_path / "factory.db"))
    r.init_schema()
    yield r
    r.close()


# ── build_reasoning_provider ────────────────────────────────────────────────


def test_stub_mode_returns_test_llm(repo, clock):
    settings = Settings(reasoning_mode="stub")
    provider = factory.build_reasoning_provider(settings, repo, clock)
    assert isinstance(provider, TestLLMProvider)


def test_test_llm_alias_returns_test_llm(repo, clock):
    settings = Settings(reasoning_mode="test_llm")
    provider = factory.build_reasoning_provider(settings, repo, clock)
    assert isinstance(provider, TestLLMProvider)


def test_hybrid_mode_returns_broker_with_fallback(repo, clock):
    settings = Settings(reasoning_mode="hybrid", reasoning_timeout_polls=3)
    provider = factory.build_reasoning_provider(settings, repo, clock)
    assert isinstance(provider, BrokerReasoningProvider)
    assert provider.allow_fallback is True
    assert isinstance(provider.fallback, TestLLMProvider)
    assert provider.timeout_polls == 3
    # The broker still answers (via the fallback) when no worker is connected.
    assert provider.capabilities() == {"text", "vision"}


def test_agent_only_mode_disables_fallback(repo, clock):
    settings = Settings(reasoning_mode="agent_only")
    provider = factory.build_reasoning_provider(settings, repo, clock)
    assert isinstance(provider, BrokerReasoningProvider)
    assert provider.allow_fallback is False
    assert isinstance(provider.fallback, TestLLMProvider)


def test_unknown_mode_defaults_to_hybrid(repo, clock):
    settings = Settings(reasoning_mode="something-else")
    provider = factory.build_reasoning_provider(settings, repo, clock)
    assert isinstance(provider, BrokerReasoningProvider)
    assert provider.allow_fallback is True


def test_explicit_fallback_is_used(repo, clock):
    sentinel = TestLLMProvider()
    settings = Settings(reasoning_mode="hybrid")
    provider = factory.build_reasoning_provider(
        settings, repo, clock, fallback=sentinel
    )
    assert isinstance(provider, BrokerReasoningProvider)
    assert provider.fallback is sentinel


def test_returned_provider_satisfies_protocol(repo, clock):
    for mode in ("stub", "hybrid", "agent_only"):
        provider = factory.build_reasoning_provider(
            Settings(reasoning_mode=mode), repo, clock
        )
        assert isinstance(provider, ReasoningProvider)


# ── build_payment_provider ──────────────────────────────────────────────────


def test_payment_default_is_test_link():
    payment = factory.build_payment_provider(Settings(payment_mode="test_link"))
    assert isinstance(payment, TestLinkProvider)
    assert isinstance(payment, PaymentProvider)


def test_payment_link_cli_selects_link_cli_dry_run():
    settings = Settings(payment_mode="link_cli", link_mode="dry_run")
    payment = factory.build_payment_provider(settings)
    assert isinstance(payment, LinkCliProvider)
    assert payment.link_mode == "dry_run"


def test_payment_link_cli_passes_link_mode_through():
    settings = Settings(payment_mode="link_cli", link_mode="live")
    payment = factory.build_payment_provider(settings)
    assert isinstance(payment, LinkCliProvider)
    assert payment.link_mode == "live"


def test_payment_factory_matches_get_payment_provider():
    from pact.payment import get_payment_provider

    settings = Settings(payment_mode="link_cli", link_mode="dry_run")
    direct = get_payment_provider(settings)
    viafac = factory.build_payment_provider(settings)
    assert type(direct) is type(viafac)


# ── main.build_app wiring (smoke) ───────────────────────────────────────────


def test_build_app_returns_fastapi(tmp_path, monkeypatch):
    # Point at a throwaway DB so the smoke test never touches the repo's default
    # pact.db, and pin to demo clock so no real-time ticker spins up.
    monkeypatch.setenv("PACT_DB_PATH", str(tmp_path / "smoke.db"))
    monkeypatch.setenv("PACT_CLOCK_MODE", "demo")
    import pact.main as main

    app = main.build_app()
    assert isinstance(app, FastAPI)


def test_build_app_uses_factory_for_hybrid(tmp_path, monkeypatch):
    # In hybrid mode build_app must wire a BrokerReasoningProvider (not the bare
    # TestLLMProvider it used to hardcode). We assert via the factory call,
    # capturing the provider it produces.
    monkeypatch.setenv("PACT_DB_PATH", str(tmp_path / "hybrid.db"))
    monkeypatch.setenv("PACT_CLOCK_MODE", "demo")
    monkeypatch.setenv("PACT_REASONING_MODE", "hybrid")
    import pact.main as main

    captured = {}
    real_build = factory.build_reasoning_provider

    def spy(settings, repo, clock, fallback=None):
        provider = real_build(settings, repo, clock, fallback=fallback)
        captured["provider"] = provider
        return provider

    monkeypatch.setattr(main, "build_reasoning_provider", spy)
    app = main.build_app()
    assert isinstance(app, FastAPI)
    assert isinstance(captured["provider"], BrokerReasoningProvider)


def test_build_app_link_cli_payment(tmp_path, monkeypatch):
    monkeypatch.setenv("PACT_DB_PATH", str(tmp_path / "pay.db"))
    monkeypatch.setenv("PACT_CLOCK_MODE", "demo")
    monkeypatch.setenv("PACT_PAYMENT_MODE", "link_cli")
    import pact.main as main

    captured = {}
    real_build = factory.build_payment_provider

    def spy(settings):
        payment = real_build(settings)
        captured["payment"] = payment
        return payment

    monkeypatch.setattr(main, "build_payment_provider", spy)
    app = main.build_app()
    assert isinstance(app, FastAPI)
    assert isinstance(captured["payment"], LinkCliProvider)
```

- [ ] **Step 2: Run the test (expect FAIL)**

```
uv run pytest tests/test_factory.py -v
```

Expected: collection error / FAIL — `ModuleNotFoundError: No module named 'pact.factory'` (the module does not exist yet), and once that is fixed the `main`-spy tests fail because `main.build_reasoning_provider` / `main.build_payment_provider` are not yet imported into `main`.

- [ ] **Step 3: Minimal implementation — create `src/pact/factory.py`**

Create `src/pact/factory.py` exactly:

```python
from __future__ import annotations

from pact.clock import Clock
from pact.config import Settings
from pact.payment import PaymentProvider, get_payment_provider
from pact.reasoning import (
    BrokerReasoningProvider,
    ReasoningProvider,
    TestLLMProvider,
)
from pact.repository import Repository


def build_reasoning_provider(
    settings: Settings,
    repo: Repository,
    clock: Clock,
    fallback: ReasoningProvider | None = None,
) -> ReasoningProvider:
    """Select the reasoning provider from Settings.

    ARCHITECTURE (locked): the brain is a Hermes AGENT, never a backend
    model/LLM client. ``TestLLMProvider`` is the deterministic stub/fallback
    only.

    Modes:
      - ``"stub"`` / ``"test_llm"`` -> the deterministic ``TestLLMProvider``.
      - ``"hybrid"`` (default) -> a ``BrokerReasoningProvider`` that enqueues the
        task for a connected agent/worker, polls ``settings.reasoning_timeout_polls``
        times, then FALLS BACK to ``TestLLMProvider`` so the app always answers.
      - ``"agent_only"`` -> the same broker provider with ``allow_fallback=False``;
        if no agent posts a result it raises ``ReasoningUnavailable`` instead of
        silently using the stub.

    ``fallback`` overrides the default ``TestLLMProvider`` instance (used by the
    broker modes); pass it to share one stub across providers.
    """
    mode = settings.reasoning_mode
    if mode in ("stub", "test_llm"):
        return TestLLMProvider()

    fb = fallback if fallback is not None else TestLLMProvider()
    allow_fallback = mode != "agent_only"
    return BrokerReasoningProvider(
        repo,
        clock,
        fallback=fb,
        timeout_polls=settings.reasoning_timeout_polls,
        allow_fallback=allow_fallback,
    )


def build_payment_provider(settings: Settings) -> PaymentProvider:
    """Select the payment provider from Settings.

    Delegates to ``payment.get_payment_provider`` (test_link by default,
    link_cli — dry-run by default — when ``payment_mode == "link_cli"``). No
    real money or network: the live link-cli path is gated inside
    ``LinkCliProvider`` and never auto-executed.
    """
    return get_payment_provider(settings)
```

- [ ] **Step 4: Minimal implementation — rewire `src/pact/main.py`**

Replace the whole file so `build_app()` calls the factory. Note: `build_reasoning_provider` and `build_payment_provider` are imported into `main`'s namespace (not called via `factory.`) so tests can `monkeypatch.setattr(main, ...)`. The `TestLLMProvider` / `TestLinkProvider` imports are dropped — they are no longer referenced here.

```python
from __future__ import annotations

import os
from datetime import datetime

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock, RealClock
from pact.config import load_settings
from pact.factory import build_payment_provider, build_reasoning_provider
from pact.repository import Repository


def build_app():
    # Read configuration from the process environment so PACT_CLOCK_MODE=demo (and the
    # other PACT_* knobs) take effect at startup. load_settings() defaults to an empty
    # mapping, so without this the server always runs with the RealClock and the demo
    # advance-day/reset endpoints 409.
    settings = load_settings(os.environ)
    repo = Repository.connect(settings.db_path)
    repo.init_schema()
    if settings.clock_mode == "demo":
        clock = FixedClock(datetime.fromisoformat(settings.demo_seed_iso))
    else:
        clock = RealClock()
    # Config-driven selection (locked: brain is a Hermes agent; TestLLMProvider is
    # only the deterministic stub/fallback). build_reasoning_provider returns the
    # stub directly in stub/test_llm mode and a BrokerReasoningProvider (which
    # enqueues for a connected agent + falls back) in hybrid/agent_only mode.
    provider = build_reasoning_provider(settings, repo, clock)
    payment = build_payment_provider(settings)
    tokens = TokenStore()
    return create_app(repo, provider, payment, tokens, clock, settings)


app = build_app()
```

Note: `create_app`'s signature and behavior are unchanged — `build_app` still calls `create_app(repo, provider, payment, tokens, clock, settings)` with the same argument order, so all existing API/flow tests stay green. The lifespan/startup-reconciliation + ticker wiring is a SEPARATE Tier-1 task; do not add it here.

- [ ] **Step 5: Run the test (expect PASS)**

```
uv run pytest tests/test_factory.py -v
```

Expected: PASS — all `build_reasoning_provider`, `build_payment_provider`, and `build_app` smoke/spy tests green.

- [ ] **Step 6: Run the full suite (existing tests stay green)**

```
uv run pytest -q
```

Expected: PASS — the previously-passing suite (254 baseline plus any tests added by earlier Tier-1 tasks) still passes; `build_app()` builds an app exactly as before, just sourcing the providers from the factory. `tests/test_smoke.py` and the `test_api_*` suites are unaffected because `create_app` is called identically.

- [ ] **Step 7: Commit**

```
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' add src/pact/factory.py src/pact/main.py tests/test_factory.py
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' commit -m "$(cat <<'EOF'
feat: config-driven provider/payment factory + main wiring

Add factory.build_reasoning_provider (stub|hybrid|agent_only) and
build_payment_provider (delegates get_payment_provider). Rewire
main.build_app to source providers from the factory instead of
hardcoding TestLLMProvider()/TestLinkProvider(). create_app signature
unchanged; existing suite stays green.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

**Call sites updated by this task:**
- `src/pact/main.py::build_app` — was `provider = TestLLMProvider()` / `payment = TestLinkProvider()`; now `provider = build_reasoning_provider(settings, repo, clock)` / `payment = build_payment_provider(settings)`. The imports of `TestLLMProvider` and `TestLinkProvider` are removed from `main.py` and replaced with `from pact.factory import build_payment_provider, build_reasoning_provider`. No other module imports these symbols from `main`, so there are no further call sites to update.


### Task 4: HTTP worker client + serve_http

Implements the HTTP-backed worker so a real Hermes agent (or the deterministic `TestLLMProvider` stub) can drain the LIVE server's reasoning-task queue over the `/api/reasoning-tasks` routes. `HttpWorkerClient` wraps a sync `httpx.Client`; `serve_http` polls pending tasks, claims only those the provider can handle, resolves them, and posts the result back. Tests drive everything against an in-process ASGI app via `httpx.ASGITransport` — no real network, no subprocess, no sleep.

**Files:**
- Create: `src/pact/httpworker.py`
- Test: `tests/test_httpworker.py`

(No existing signatures change in this task; `serve_http`/`relay_outbox` are additive. `relay_outbox` is included here because the contract groups it with the HTTP worker; the CLI in Task 5 consumes it.)

---

- [ ] **Step 1: Write the failing test**

Create `tests/test_httpworker.py`. It builds the real app exactly like `tests/test_api_broker.py` (`Repository.connect` + `init_schema`, `TestLLMProvider`, `TestLinkProvider`, `TokenStore`, `FixedClock`, `Settings`), wires a SYNC `httpx.Client` to it via `httpx.ASGITransport`, drafts a pact through the API, enqueues tasks through the API, then exercises `HttpWorkerClient` + `serve_http`. A sync `httpx.Client` over `ASGITransport` runs the ASGI app without a caller-managed event loop, so these tests are plain (non-async) functions.

```python
from datetime import datetime, timezone

import httpx
import pytest

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.broker import get_result
from pact.clock import FixedClock
from pact.config import Settings
from pact.httpworker import HttpWorkerClient, serve_http
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def _build(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
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
    return httpx.Client(transport=transport, base_url="http://test")


def _draft_pact(http, prompt):
    r = http.post("/api/pacts/draft", json={"prompt": prompt})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _enqueue(http, pact_id, type, input, required_capability=None):
    r = http.post(
        f"/api/pacts/{pact_id}/reasoning-tasks",
        json={
            "type": type,
            "input": input,
            "required_capability": required_capability,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_pending_claim_post_result_roundtrip(tmp_path):
    app, _ = _build(tmp_path)
    with _client(app) as http:
        pact_id = _draft_pact(http, "do a thing 5x this week or $15 to charity")
        tid = _enqueue(
            http,
            pact_id,
            "judge_proof",
            {"token_ok": True, "is_duplicate": False, "content_ok": True},
            required_capability="vision",
        )

        client = HttpWorkerClient(base_url="http://test", http=http)

        # pending() surfaces the enqueued task.
        pending = client.pending(capability="vision")
        assert tid in [t["id"] for t in pending]

        # claim() flips it to claimed by this agent.
        claimed = client.claim(tid, "worker-1", ["text", "vision"])
        assert claimed["status"] == "claimed"
        assert claimed["claimed_by"] == "worker-1"

        # post_result() flips it to done with the payload.
        done = client.post_result(tid, {"status": "passed", "reason": "ok"})
        assert done["status"] == "done"
        assert done["result"] == {"status": "passed", "reason": "ok"}


def test_serve_http_claims_and_posts_a_result(tmp_path):
    app, repo = _build(tmp_path)
    with _client(app) as http:
        pact_id = _draft_pact(http, "do a thing 5x this week or $15 to charity")
        tid = _enqueue(
            http,
            pact_id,
            "judge_proof",
            {"token_ok": True, "is_duplicate": False, "content_ok": True},
            required_capability="vision",
        )

        client = HttpWorkerClient(base_url="http://test", http=http)
        resolved = serve_http(
            client,
            TestLLMProvider(),
            agent_name="worker-1",
            max_rounds=1,
        )
        assert resolved == 1

        # The API can read the posted result: the task is done with the
        # provider's deterministic judge_proof verdict.
        result = get_result(repo, tid)
        assert result is not None
        assert result["status"] == "passed"
        assert result["checklist"] == {"token": True, "content": True, "not_dup": True}

        # No longer pending.
        assert tid not in [t["id"] for t in client.pending()]


def test_serve_http_skips_capability_mismatch_without_claiming(tmp_path):
    app, repo = _build(tmp_path)
    with _client(app) as http:
        pact_id = _draft_pact(http, "do a thing 5x this week or $15 to charity")
        # TestLLMProvider has {"text", "vision"} only; "audio" is unhandleable.
        tid = _enqueue(
            http,
            pact_id,
            "judge_proof",
            {"token_ok": True, "is_duplicate": False, "content_ok": True},
            required_capability="audio",
        )

        client = HttpWorkerClient(base_url="http://test", http=http)
        resolved = serve_http(
            client,
            TestLLMProvider(),
            agent_name="worker-1",
            max_rounds=1,
        )
        assert resolved == 0

        # Never claimed: still pending, no result.
        assert tid in [t["id"] for t in client.pending()]
        assert get_result(repo, tid) is None


def test_serve_http_resolves_only_handleable_when_mixed(tmp_path):
    app, repo = _build(tmp_path)
    with _client(app) as http:
        pact_id = _draft_pact(http, "do a thing 5x this week or $15 to charity")
        handleable = _enqueue(
            http,
            pact_id,
            "coach",
            {"valid": 1, "target": 5, "days_left": 3, "charity": "WCK"},
            required_capability="text",
        )
        unhandleable = _enqueue(
            http,
            pact_id,
            "judge_proof",
            {"token_ok": True, "is_duplicate": False, "content_ok": True},
            required_capability="audio",
        )

        client = HttpWorkerClient(base_url="http://test", http=http)
        resolved = serve_http(
            client,
            TestLLMProvider(),
            agent_name="worker-1",
            max_rounds=1,
        )
        assert resolved == 1

        assert get_result(repo, handleable) is not None
        assert get_result(repo, unhandleable) is None
        assert unhandleable in [t["id"] for t in client.pending()]


def test_serve_http_returns_zero_when_queue_empty(tmp_path):
    app, _ = _build(tmp_path)
    with _client(app) as http:
        client = HttpWorkerClient(base_url="http://test", http=http)
        resolved = serve_http(
            client,
            TestLLMProvider(),
            agent_name="worker-1",
            max_rounds=3,
        )
        assert resolved == 0
```

- [ ] **Step 2: Run the test — expect FAIL**

```
uv run pytest tests/test_httpworker.py -v
```

Expected: collection/import error / FAIL — `ModuleNotFoundError: No module named 'pact.httpworker'` (the module and its `HttpWorkerClient`/`serve_http` do not exist yet).

- [ ] **Step 3: Write the minimal implementation**

Create `src/pact/httpworker.py`. `HttpWorkerClient` defaults to a real `httpx.Client(base_url=base_url)` when no client is injected; tests inject one bound to the ASGI app. `serve_http` reconstructs a `ReasoningTask` from the claim response so it can call `provider.resolve(task)` with the same object shape the in-process worker uses. Capability checks mirror `worker._can_handle`: a task with `required_capability=None` is always handleable; otherwise the provider must hold that capability. Mismatched tasks are skipped BEFORE claiming, so they stay pending.

```python
"""HTTP-backed reasoning worker: drain a LIVE server's broker queue over HTTP.

This is the runnable worker a Hermes agent (or the deterministic
``TestLLMProvider`` stub) uses against a running Pact API. It only touches the
``/api/reasoning-tasks`` routes — it never moves money or delivers coaching
nudges (those live behind the scheduler/outbox). ``relay_outbox`` is the
companion that drains ``/api/outbox`` and marks each message delivered.

Determinism: every method is a single synchronous HTTP round-trip. Tests inject
an ``httpx.Client`` wired to an in-process ASGI app via ``httpx.ASGITransport``,
so there is no real network, subprocess, or sleep.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

import httpx

from .models import ReasoningTask, TaskStatus, TaskType
from .reasoning import ReasoningProvider


class HttpWorkerClient:
    """Thin sync HTTP client over the broker's reasoning-task routes."""

    def __init__(self, base_url: str, http: httpx.Client | None = None) -> None:
        self.base_url = base_url
        # Tests inject an httpx.Client bound to the ASGI app; otherwise talk to
        # a real server at base_url.
        self.http = http if http is not None else httpx.Client(base_url=base_url)

    def pending(self, capability: str | None = None) -> list[dict]:
        params = {} if capability is None else {"capability": capability}
        r = self.http.get("/api/reasoning-tasks", params=params)
        r.raise_for_status()
        return r.json()

    def claim(self, task_id: str, agent_name: str, capabilities) -> dict:
        r = self.http.post(
            f"/api/reasoning-tasks/{task_id}/claim",
            json={"agent_name": agent_name, "capabilities": list(capabilities)},
        )
        r.raise_for_status()
        return r.json()

    def post_result(self, task_id: str, result: dict) -> dict:
        r = self.http.post(
            f"/api/reasoning-tasks/{task_id}/result",
            json={"result": result},
        )
        r.raise_for_status()
        return r.json()


def _can_handle(required_capability: str | None, capabilities: set[str]) -> bool:
    """Mirror worker._can_handle: no requirement, or a capability we hold."""
    if required_capability is None:
        return True
    return required_capability in capabilities


def _task_from_dict(data: dict) -> ReasoningTask:
    """Rebuild a ReasoningTask from a claim/list response payload."""
    return ReasoningTask(
        id=data["id"],
        pact_id=data.get("pact_id"),
        type=TaskType(data["type"]),
        required_capability=data.get("required_capability"),
        input=data.get("input", {}),
        status=TaskStatus(data["status"]),
        result=data.get("result"),
        claimed_by=data.get("claimed_by"),
        created_at=datetime.fromisoformat(data["created_at"]),
    )


def serve_http(
    client: HttpWorkerClient,
    provider: ReasoningProvider,
    agent_name: str,
    max_rounds: int = 1,
) -> int:
    """Drain pending tasks this provider can handle, over HTTP.

    Loops up to ``max_rounds`` times: list pending tasks; for each task whose
    required capability the provider holds, claim it, resolve it, and post the
    result back. Capability-mismatch tasks are SKIPPED without claiming (left
    pending for a more-capable worker). Returns the number of tasks resolved.

    A round that resolves nothing stops the loop early (queue drained for us).
    """
    capabilities = provider.capabilities()
    resolved = 0
    for _ in range(max_rounds):
        count_this_round = 0
        for entry in client.pending():
            if not _can_handle(entry.get("required_capability"), capabilities):
                continue
            claimed = client.claim(entry["id"], agent_name, capabilities)
            task = _task_from_dict(claimed)
            result = provider.resolve(task)
            client.post_result(task.id, result)
            resolved += 1
            count_this_round += 1
        if count_this_round == 0:
            break
    return resolved


def relay_outbox(
    client_or_http,
    base_url: str,
    owner: str,
    deliver: Callable[[dict], object] | None = None,
) -> int:
    """Drain the owner's outbox: deliver each nudge, then mark it delivered.

    ``client_or_http`` may be an ``HttpWorkerClient`` (its ``.http`` is used) or
    a bare ``httpx.Client``. ``deliver`` is called once per message (default: a
    no-op that just returns the message, e.g. logging in a real agent). Returns
    the number of messages relayed.
    """
    http = getattr(client_or_http, "http", client_or_http)
    if deliver is None:
        def deliver(msg: dict) -> dict:
            return msg
    r = http.get("/api/outbox", params={"owner": owner})
    r.raise_for_status()
    messages = r.json()
    relayed = 0
    for msg in messages:
        deliver(msg)
        d = http.post(f"/api/coach/{msg['id']}/delivered")
        d.raise_for_status()
        relayed += 1
    return relayed
```

- [ ] **Step 4: Run the test — expect PASS**

```
uv run pytest tests/test_httpworker.py -v
```

Expected: PASS — all five tests green. Then confirm no regression across the suite:

```
uv run pytest -q
```

Expected: the full suite still passes (254 prior tests + the 5 new ones).

- [ ] **Step 5: Commit**

```
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' add src/pact/httpworker.py tests/test_httpworker.py
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' commit -m "$(cat <<'EOF'
feat(worker): HTTP worker client + serve_http over /api/reasoning-tasks

HttpWorkerClient (pending/claim/post_result) lets a Hermes agent or the
TestLLMProvider stub drain a live server's broker queue over HTTP.
serve_http claims+resolves+posts only handleable tasks and skips
capability-mismatch tasks without claiming. Also adds relay_outbox for
the outbox->delivered relay. Tested in-process via httpx.ASGITransport;
no network, subprocess, or sleep.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

**Notes / call sites:**
- No existing signatures change. `serve_http` and `relay_outbox` are consumed by `src/pact/cli.py` in Task 5 (`pact serve` -> `serve_http`; `pact outbox` -> `relay_outbox`).
- `_task_from_dict` relies on the claim response carrying the full `ReasoningTask` dump (`id`, `pact_id`, `type`, `required_capability`, `input`, `status`, `result`, `claimed_by`, `created_at`) — confirmed against `api.py`'s `claim_reasoning_task` returning `task.model_dump(mode="json")` and the `ReasoningTask` model in `models.py`.
- Capability handling matches `worker._can_handle`: `required_capability=None` is universally handleable; `TestLLMProvider.capabilities()` is `{"text", "vision"}`, so an `"audio"` task is skipped.


### Task 5: Outbox relay + pact CLI

Wire the runnable surface a Hermes agent (or the deterministic stub) uses against a **live** Pact server: relay queued coaching nudges over HTTP and expose a `pact` console entrypoint with `serve` / `tick` / `outbox` subcommands. All tests drive an in-process ASGI app through an injected `httpx.Client` (`httpx.ASGITransport`) — no real network, no subprocess, no `time.sleep`.

This task assumes `src/pact/httpworker.py` already exists with `HttpWorkerClient` and `serve_http(...)` (Task 4). Here we **append** `relay_outbox(...)` to it, create `src/pact/cli.py`, and register the `[project.scripts]` entrypoint.

**Files:**
- Modify: `/Users/chadd_mini/hermes-projects/pact/src/pact/httpworker.py` (append `relay_outbox`)
- Create: `/Users/chadd_mini/hermes-projects/pact/src/pact/cli.py`
- Modify: `/Users/chadd_mini/hermes-projects/pact/pyproject.toml` (add `[project.scripts]`)
- Test: `/Users/chadd_mini/hermes-projects/pact/tests/test_cli.py`

---

- [ ] **Step 1: Write the failing test**

Create `/Users/chadd_mini/hermes-projects/pact/tests/test_cli.py`. It builds a real `create_app(...)` over an in-memory repo, seeds a behind-pace active pact, runs `scheduler.tick` once to drop a nudge into the outbox, then drives `relay_outbox` and `cli.main([...])` through a **sync** `httpx.Client` wired to the ASGI app via `httpx.ASGITransport`. The CLI subcommands accept an injected `http=` client so no real network is used.

```python
"""Tests for the outbox relay helper and the `pact` CLI entrypoint.

Everything runs against an in-process ASGI app through an injected sync
httpx.Client (httpx.ASGITransport) — no real network, subprocess, or sleep.
"""
from datetime import datetime, timedelta, timezone

import httpx

from pact import cli
from pact.anticheat import TokenStore
from pact.api import create_app
from pact.charities import CHARITIES
from pact.clock import FixedClock
from pact.config import Settings
from pact.httpworker import HttpWorkerClient, relay_outbox
from pact.models import Modality, Pact, PactStatus, Rubric, StakeState
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository
from pact.scheduler import tick

OWNER = "colehaddad40@gmail.com"


def _repo() -> Repository:
    repo = Repository.connect(":memory:")
    repo.init_schema()
    return repo


def _rubric() -> Rubric:
    return Rubric(
        modality=Modality.photo,
        must_show=["person mid-exercise"],
        min_distinct_days=5,
        count_target=5,
    )


def _active_pact(pact_id: str, now: datetime, deadline: datetime) -> Pact:
    charity = CHARITIES[0]
    return Pact(
        id=pact_id,
        owner=OWNER,
        original_prompt="work out 5x or $5 to charity",
        title="Work out 5x",
        goal="Complete 5 workout sessions on 5 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=deadline,
        target_count=5,
        distinct_days=True,
        recommended_stake_cents=500,
        stake_amount_cents=500,
        charity_id=charity["id"],
        charity_url=charity["donation_url"],
        freezes_allowed=1,
        rubric=_rubric(),
        status=PactStatus.active,
        stake_state=StakeState.committed,
        created_at=now - timedelta(days=2),
        started_at=now - timedelta(days=2),
    )


def _app_with_nudge():
    """Build an app + repo and seed exactly one undelivered outbox nudge."""
    now = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(now)
    repo = _repo()
    payment = TestLinkProvider()
    settings = Settings()
    deadline = now + timedelta(days=2)
    repo.save_pact(_active_pact("pact_cli_relay", now, deadline))
    summary = tick(repo, clock, payment, settings)
    assert "pact_cli_relay" in summary["nudged"]
    app = create_app(repo, TestLLMProvider(), payment, TokenStore(), clock, settings)
    return app, repo


def _sync_client(app) -> httpx.Client:
    transport = httpx.ASGITransport(app=app)
    return httpx.Client(transport=transport, base_url="http://test")


def test_relay_outbox_delivers_and_marks_each_nudge():
    """relay_outbox GETs the outbox, delivers each msg, marks it delivered."""
    app, repo = _app_with_nudge()
    delivered_bodies = []

    with _sync_client(app) as http:
        client = HttpWorkerClient("http://test", http=http)
        count = relay_outbox(
            client,
            "http://test",
            OWNER,
            deliver=lambda msg: delivered_bodies.append(msg["body"]),
        )

    # Exactly one nudge was relayed, deliver() saw its body...
    assert count == 1
    assert len(delivered_bodies) == 1
    assert "left" in delivered_bodies[0]  # coach copy: "...N days left..."

    # ...and the backend now reports an empty outbox (message marked delivered).
    assert repo.outbox(OWNER) == []


def test_relay_outbox_empty_returns_zero():
    """An empty outbox relays nothing and calls deliver() zero times."""
    app, repo = _app_with_nudge()
    # Drain the one nudge first via a no-op relay.
    with _sync_client(app) as http:
        client = HttpWorkerClient("http://test", http=http)
        relay_outbox(client, "http://test", OWNER, deliver=lambda msg: None)

    calls = []
    with _sync_client(app) as http:
        client = HttpWorkerClient("http://test", http=http)
        count = relay_outbox(
            client, "http://test", OWNER, deliver=lambda msg: calls.append(msg)
        )
    assert count == 0
    assert calls == []


def test_relay_outbox_default_deliver_is_noop_logger():
    """relay_outbox works with no deliver= (default just relays+marks)."""
    app, repo = _app_with_nudge()
    with _sync_client(app) as http:
        client = HttpWorkerClient("http://test", http=http)
        count = relay_outbox(client, "http://test", OWNER)
    assert count == 1
    assert repo.outbox(OWNER) == []


def test_cli_outbox_subcommand_relays_nudge():
    """`pact outbox --owner ...` relays the queued nudge and returns 0 (success)."""
    app, repo = _app_with_nudge()
    with _sync_client(app) as http:
        rc = cli.main(
            ["outbox", "--base-url", "http://test", "--owner", OWNER],
            http=http,
        )
    assert rc == 0
    assert repo.outbox(OWNER) == []


def test_cli_tick_subcommand_calls_api_tick():
    """`pact tick` POSTs /api/tick and returns the scheduler summary shape."""
    app, repo = _app_with_nudge()
    captured = {}

    def _capture(summary):
        captured.update(summary)

    with _sync_client(app) as http:
        rc = cli.main(
            ["tick", "--base-url", "http://test"],
            http=http,
            on_result=_capture,
        )
    assert rc == 0
    # The scheduler summary always carries these idempotent-pass keys.
    assert set(["now", "settled", "donated", "nudged"]).issubset(captured.keys())


def test_cli_serve_subcommand_drains_pending_task():
    """`pact serve --rounds 1` resolves one enqueued reasoning task via serve_http."""
    app, repo = _app_with_nudge()
    # Enqueue a draft task the default TestLLMProvider can handle (no capability req).
    with _sync_client(app) as http:
        resp = http.post(
            "/api/pacts/pact_cli_relay/reasoning-tasks",
            json={"type": "draft", "input": {"prompt": "run a mile"}},
        )
        assert resp.status_code == 200
        rc = cli.main(
            [
                "serve",
                "--base-url",
                "http://test",
                "--agent-name",
                "test-agent",
                "--capabilities",
                "text,vision",
                "--rounds",
                "1",
            ],
            http=http,
        )
    assert rc == 0
    # The task is now done with a draft result (TestLLMProvider resolved it).
    from pact.broker import get_result

    pending = repo.pending_tasks()
    assert pending == []  # claimed+resolved, no longer pending


def test_cli_unknown_subcommand_returns_nonzero():
    """An unknown subcommand exits non-zero without raising."""
    rc = cli.main(["bogus"])
    assert rc != 0
```

- [ ] **Step 2: Run the test — expect FAIL**

```
uv run pytest tests/test_cli.py -v
```

Expected: **FAIL** — `ImportError: cannot import name 'relay_outbox' from 'pact.httpworker'` and `ModuleNotFoundError: No module named 'pact.cli'`. (Tests error at collection.)

- [ ] **Step 3: Implement `relay_outbox` in `httpworker.py`**

Append `relay_outbox` to `/Users/chadd_mini/hermes-projects/pact/src/pact/httpworker.py`. It uses the existing `HttpWorkerClient`'s underlying `httpx.Client` (`client.http`) to GET the outbox and POST delivered. The signature is `relay_outbox(client_or_http, base_url, owner, deliver=None)`: it accepts either an `HttpWorkerClient` (pulls `.http`) or a raw `httpx.Client`, so the CLI and tests can pass whichever they have.

```python
def relay_outbox(client_or_http, base_url, owner, deliver=None) -> int:
    """Relay the owner's undelivered coaching nudges out of the live server.

    For each message in GET /api/outbox?owner=<owner>: call ``deliver(msg)``
    (the Hermes agent ships it over its own channel; the default just returns
    the message, i.e. a no-op log), then POST /api/coach/{id}/delivered so it
    leaves the outbox. Returns the number of messages relayed.

    ``client_or_http`` may be an :class:`HttpWorkerClient` (its ``.http`` is
    used) or a raw ``httpx.Client``. ``base_url`` is accepted for symmetry with
    the CLI and prepended only when the http client has no ``base_url`` of its
    own; in the in-process ASGI tests the client is already bound to the app's
    base_url, so the relative paths below resolve correctly.
    """
    http = getattr(client_or_http, "http", client_or_http)
    if deliver is None:
        def deliver(msg):  # default: no-op "log" that just echoes the message
            return msg

    resp = http.get("/api/outbox", params={"owner": owner})
    resp.raise_for_status()
    messages = resp.json()

    relayed = 0
    for msg in messages:
        deliver(msg)
        marked = http.post(f"/api/coach/{msg['id']}/delivered")
        marked.raise_for_status()
        relayed += 1
    return relayed
```

Note: this uses `getattr(client_or_http, "http", client_or_http)` so passing the `HttpWorkerClient` (which holds `.http`, per Task 4's `__init__(self, base_url, http=None)`) or a bare `httpx.Client` both work. The `base_url` argument is intentionally unused for path-building because the injected `httpx.Client` already carries `base_url="http://test"` (relative paths resolve against it); in production the client is constructed with the real base URL.

- [ ] **Step 4: Implement `cli.py`**

Create `/Users/chadd_mini/hermes-projects/pact/src/pact/cli.py`. `main(argv=None, *, http=None, on_result=None)` parses subcommands and wires each to `serve_http` / `POST /api/tick` / `relay_outbox`. The `http=` and `on_result=` keyword args are test seams (inject the ASGI-backed client; capture the tick summary) — real invocations construct a fresh `httpx.Client(base_url=...)` and print.

```python
"""The ``pact`` console entrypoint.

Subcommands drive a LIVE Pact server over HTTP:

    pact serve   — run the reasoning worker loop (serve_http) against the queue.
                   The default reasoning provider is the deterministic
                   TestLLMProvider; a real Hermes agent instead reasons inline
                   (/pact skill) and posts results, so it does not run this.
    pact tick    — POST /api/tick once (one scheduler sweep).
    pact outbox  — relay the owner's queued coaching nudges (relay_outbox).

Everything goes through an injectable httpx.Client so tests can bind it to an
in-process ASGI app (httpx.ASGITransport) — no real network or subprocess.
"""
from __future__ import annotations

import argparse

import httpx

from .httpworker import HttpWorkerClient, relay_outbox, serve_http
from .reasoning import TestLLMProvider


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pact")
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="run the reasoning worker loop")
    p_serve.add_argument("--base-url", default="http://localhost:8000")
    p_serve.add_argument("--agent-name", default="pact-worker")
    p_serve.add_argument(
        "--capabilities",
        default="text,vision",
        help="comma-separated capabilities this worker advertises",
    )
    p_serve.add_argument("--rounds", type=int, default=1)

    p_tick = sub.add_parser("tick", help="run one scheduler sweep (POST /api/tick)")
    p_tick.add_argument("--base-url", default="http://localhost:8000")

    p_outbox = sub.add_parser("outbox", help="relay queued coaching nudges")
    p_outbox.add_argument("--base-url", default="http://localhost:8000")
    p_outbox.add_argument("--owner", required=True)

    return parser


def main(argv=None, *, http=None, on_result=None) -> int:
    """Entry point. ``http`` injects an httpx.Client (tests bind it to an ASGI
    app); ``on_result`` (tests) receives the JSON payload of network calls in
    lieu of printing. Returns a process exit code (0 on success)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 2

    own_client = http is None
    client = http if http is not None else httpx.Client(base_url=args.base_url)
    try:
        if args.command == "serve":
            capabilities = [
                c.strip() for c in args.capabilities.split(",") if c.strip()
            ]
            worker = HttpWorkerClient(args.base_url, http=client)
            resolved = serve_http(
                worker,
                TestLLMProvider(),
                args.agent_name,
                max_rounds=args.rounds,
            )
            if on_result is not None:
                on_result({"resolved": resolved})
            else:
                print(f"resolved {resolved} reasoning task(s)")
            return 0

        if args.command == "tick":
            resp = client.post("/api/tick")
            resp.raise_for_status()
            summary = resp.json()
            if on_result is not None:
                on_result(summary)
            else:
                print(summary)
            return 0

        if args.command == "outbox":
            worker = HttpWorkerClient(args.base_url, http=client)
            relayed = relay_outbox(worker, args.base_url, args.owner)
            if on_result is not None:
                on_result({"relayed": relayed})
            else:
                print(f"relayed {relayed} coaching message(s)")
            return 0

        parser.print_help()
        return 2
    finally:
        if own_client:
            client.close()
```

If `serve_http`'s actual Task-4 signature differs (e.g. it takes `capabilities=` rather than reading them from the provider), update the `serve_http(worker, TestLLMProvider(), args.agent_name, max_rounds=args.rounds)` call here to match — the frozen contract for Task 4 is `serve_http(client, provider, agent_name, max_rounds=1) -> int`, and `provider.capabilities()` supplies the capability set used to filter+claim, so no extra capabilities arg is passed. The `--capabilities` flag is parsed for forward-compat and to document the worker's advertised set; `TestLLMProvider().capabilities()` already returns `{"text", "vision"}`.

- [ ] **Step 5: Register the `[project.scripts]` entrypoint**

Add the console-script block to `/Users/chadd_mini/hermes-projects/pact/pyproject.toml`, immediately after the `dependencies` list (before `[dependency-groups]`):

```toml
[project.scripts]
pact = "pact.cli:main"
```

After editing, the `[project]` table region should read:

```toml
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

[project.scripts]
pact = "pact.cli:main"

[dependency-groups]
dev = [
    "pytest",
    "httpx",
    "pytest-asyncio",
    "anyio[trio]",
]
```

- [ ] **Step 6: Run the test — expect PASS**

```
uv run pytest tests/test_cli.py -v
```

Expected: **PASS** — all of `test_relay_outbox_delivers_and_marks_each_nudge`, `test_relay_outbox_empty_returns_zero`, `test_relay_outbox_default_deliver_is_noop_logger`, `test_cli_outbox_subcommand_relays_nudge`, `test_cli_tick_subcommand_calls_api_tick`, `test_cli_serve_subcommand_drains_pending_task`, and `test_cli_unknown_subcommand_returns_nonzero` pass.

- [ ] **Step 7: Run the full suite — expect no regressions**

```
uv run pytest -q
```

Expected: **PASS** — the pre-existing 254 tests plus the new `tests/test_cli.py` cases. No existing signature changed (`create_app`, `serve_http`, `HttpWorkerClient`, `scheduler.tick`, the `/api/outbox` + `/api/coach/{id}/delivered` + `/api/tick` routes are all consumed as-is), so nothing else needs updating.

- [ ] **Step 8: Commit**

```
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' add src/pact/httpworker.py src/pact/cli.py pyproject.toml tests/test_cli.py
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' commit -m "$(cat <<'EOF'
feat(cli): outbox relay + `pact` serve/tick/outbox entrypoint

Add relay_outbox(client_or_http, base_url, owner, deliver) to httpworker:
GET /api/outbox -> deliver(msg) -> POST /api/coach/{id}/delivered. Add
pact.cli.main(argv) with serve (serve_http loop), tick (POST /api/tick),
and outbox (relay) subcommands, plus [project.scripts] pact = pact.cli:main.
Tests drive an in-process ASGI app via an injected sync httpx.Client
(httpx.ASGITransport) — no real network/subprocess/sleep.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```


### Task 6: Lifespan: startup reconciliation + autonomous ticker

**Files:**
- Modify: `src/pact/scheduler.py` (add a testable one-iteration helper + a cancellable loop)
- Modify: `src/pact/main.py` (attach a FastAPI lifespan in `build_app`: startup reconciliation + conditional ticker)
- Test: `tests/test_lifespan_scheduler.py` (Create)

**Context the steps rely on (verified against source):**
- `scheduler.tick(repo, clock, payment, settings) -> dict` already exists and is idempotent (`src/pact/scheduler.py`).
- `lifecycle.reconcile_on_startup(repo, clock, payment, settings) -> list[Pact]` already settles due actives + closes elapsed windows (`src/pact/lifecycle.py:481`).
- `create_app(repo, provider, payment, tokens, clock, settings) -> FastAPI` (`src/pact/api.py:93`) — its signature/behavior MUST stay unchanged. We build the lifespan in `build_app` (where `repo/payment/settings/clock` all exist) and attach it to the already-constructed `app` via `app.router.lifespan_context`, so `create_app` is untouched.
- `RealClock`/`FixedClock` live in `src/pact/clock.py`. Demo mode uses `FixedClock`; the real-time ticker must NOT run under a `FixedClock`.
- `Settings` will already carry `scheduler_enabled: bool = True` and `scheduler_interval_seconds: int = 60` from the config task; this task only consumes them. (If running this task standalone before the config task, add those two fields to `src/pact/config.py`'s `Settings` dataclass + `load_settings` first — `scheduler_enabled` from `PACT_SCHEDULER_ENABLED` (`_str(...) != "0"` style or a bool parse) and `scheduler_interval_seconds` from `PACT_SCHEDULER_INTERVAL_SECONDS`.)
- pyproject already has `asyncio_mode = "auto"`, `httpx`, `anyio[trio]`, FastAPI 0.138 (lifespan context supported). Test cmd: `uv run pytest tests/<f> -v`.

The ticker loop body is factored into `run_ticker_loop`, an async loop guarded by a `stop` `asyncio.Event` with an **injected async sleep**, so a test drives a single deterministic iteration with NO real delay. The lifespan wires `reconcile_on_startup` on startup, starts the loop as a background task only on a `RealClock` with `scheduler_enabled`, and cancels it on shutdown.

---

- [ ] **Step 1: Write the failing test**

Create `tests/test_lifespan_scheduler.py`:

```python
import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from pact.charities import CHARITIES
from pact.clock import FixedClock, RealClock
from pact.config import Settings
from pact.models import (
    Modality,
    Pact,
    PactStatus,
    Rubric,
    StakeState,
)
from pact.payment import TestLinkProvider
from pact.repository import Repository


def _repo() -> Repository:
    repo = Repository.connect(":memory:")
    repo.init_schema()
    return repo


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


# ── 1. The ticker loop helper runs exactly one tick deterministically and stops. ──
async def test_run_ticker_loop_runs_one_tick_then_stops():
    from pact.scheduler import run_ticker_loop

    start = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(start)
    repo = _repo()
    settings = Settings()
    payment = TestLinkProvider()

    # A ghosted due active pact: one tick must settle it to failed (window opens).
    repo.save_pact(_active_pact("pact_tick", start, start - timedelta(hours=1)))

    ticks: list[dict] = []
    stop = asyncio.Event()

    async def fake_sleep(seconds: float) -> None:
        # After the first tick, request shutdown so the loop exits on its next guard
        # check. No real delay — purely deterministic.
        assert seconds == settings.scheduler_interval_seconds
        stop.set()

    def record_tick():
        result = run_ticker_loop.__wrapped_tick__(repo, clock, payment, settings)
        ticks.append(result)
        return result

    # run_ticker_loop calls tick once per iteration; we count via the repo state.
    count = await run_ticker_loop(
        repo, clock, payment, settings, stop=stop, sleep=fake_sleep
    )

    assert count == 1  # exactly one tick ran before stop fired
    settled = repo.get_pact("pact_tick")
    assert settled.status == PactStatus.failed
    assert settled.spend_request_id is None
    assert settled.dispute_window_closes_at is not None


# ── 2. The loop exits immediately if stop is already set (zero ticks). ──
async def test_run_ticker_loop_pre_set_stop_runs_no_ticks():
    from pact.scheduler import run_ticker_loop

    start = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = FixedClock(start)
    repo = _repo()
    settings = Settings()
    payment = TestLinkProvider()
    repo.save_pact(_active_pact("pact_x", start, start - timedelta(hours=1)))

    stop = asyncio.Event()
    stop.set()

    async def fake_sleep(seconds: float) -> None:  # pragma: no cover - must not run
        raise AssertionError("sleep must not be called when stop is pre-set")

    count = await run_ticker_loop(
        repo, clock, payment, settings, stop=stop, sleep=fake_sleep
    )
    assert count == 0
    # Untouched: no tick ran.
    assert repo.get_pact("pact_x").status == PactStatus.active


# ── 3. Startup reconciliation settles a ghosted due pact on boot (via the lifespan). ──
async def test_lifespan_reconciles_ghosted_pact_on_startup():
    from pact.main import build_app

    start = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        # Seed a ghosted due active pact BEFORE boot, on a demo FixedClock pinned
        # past the deadline so startup reconciliation has work to do but no
        # real-time ticker spins up (demo mode).
        seed_repo = Repository.connect(path)
        seed_repo.init_schema()
        seed_repo.save_pact(
            _active_pact("pact_boot", start, start - timedelta(hours=1))
        )

        env = {
            "PACT_DB_PATH": path,
            "PACT_CLOCK_MODE": "demo",
            "PACT_DEMO_SEED_ISO": start.isoformat(),
        }
        app = build_app(env=env)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            # Entering the client context triggers the lifespan startup.
            async with app.router.lifespan_context(app):
                resp = await client.get("/api/pacts/pact_boot")
                assert resp.status_code == 200
                # Startup reconciliation ran: the ghosted pact is now failed.
                assert resp.json()["status"] == PactStatus.failed.value
                assert resp.json()["spend_request_id"] is None
                assert resp.json()["dispute_window_closes_at"] is not None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ── 4. Demo mode (FixedClock) starts NO real-time ticker. ──
async def test_demo_mode_starts_no_ticker():
    from pact.main import build_app

    start = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        env = {
            "PACT_DB_PATH": path,
            "PACT_CLOCK_MODE": "demo",
            "PACT_DEMO_SEED_ISO": start.isoformat(),
        }
        app = build_app(env=env)
        async with app.router.lifespan_context(app):
            # The lifespan records its ticker task on app.state for inspection.
            assert getattr(app.state, "ticker_task", None) is None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ── 5. Real-clock mode with scheduler_enabled starts a ticker task; shutdown cancels it. ──
async def test_real_clock_starts_and_cancels_ticker():
    from pact.main import build_app

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        env = {
            "PACT_DB_PATH": path,
            "PACT_CLOCK_MODE": "real",
            # Large interval so the background ticker sleeps after its first tick
            # and never fires a second one during the test.
            "PACT_SCHEDULER_INTERVAL_SECONDS": "3600",
        }
        app = build_app(env=env)
        async with app.router.lifespan_context(app):
            task = getattr(app.state, "ticker_task", None)
            assert task is not None
            assert not task.done()
        # Lifespan shutdown must cancel the background ticker.
        assert app.state.ticker_task.done()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
```

Note on the `run_ticker_loop.__wrapped_tick__` line in test 1: it documents intent but is NOT required by the assertions (the assertions check `count` + repo state). Remove that helper block to keep the test minimal — the canonical version below drops it.

Replace test 1's body between `stop = asyncio.Event()` and the `count = await run_ticker_loop(...)` call with just:

```python
    stop = asyncio.Event()

    async def fake_sleep(seconds: float) -> None:
        assert seconds == settings.scheduler_interval_seconds
        stop.set()

    count = await run_ticker_loop(
        repo, clock, payment, settings, stop=stop, sleep=fake_sleep
    )
```

- [ ] **Step 2: Run the test — expect FAIL**

```bash
uv run pytest tests/test_lifespan_scheduler.py -v
```

Expected FAIL: `ImportError: cannot import name 'run_ticker_loop' from 'pact.scheduler'` (and `build_app(env=...)` raises `TypeError: build_app() got an unexpected keyword argument 'env'`).

- [ ] **Step 3: Add the ticker loop helper to `src/pact/scheduler.py`**

Append at the end of `src/pact/scheduler.py` (after the existing `tick` function). Keep the existing imports; add `asyncio` and the typing/Clock imports at the top of the new block:

```python
# ─── Tier-1: autonomous ticker loop helper ─────────────────────────────────────

import asyncio
from typing import Awaitable, Callable


async def run_ticker_loop(
    repo: Repository,
    clock: Clock,
    payment: PaymentProvider,
    settings: Settings,
    *,
    stop: asyncio.Event,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    """Drive scheduler.tick on an interval until ``stop`` is set.

    One iteration = one ``tick`` followed by an awaitable ``sleep`` of
    ``settings.scheduler_interval_seconds``. The loop is guarded by ``stop`` so it
    exits cleanly on shutdown, and ``sleep`` is injected so tests pass a no-op (or
    a coroutine that sets ``stop``) and drive a single deterministic iteration with
    no real delay. ``tick`` itself is idempotent, so an extra iteration is harmless.

    Returns the number of ticks executed before ``stop`` fired (useful for tests).
    """
    ticks = 0
    while not stop.is_set():
        tick(repo, clock, payment, settings)
        ticks += 1
        if stop.is_set():
            break
        await sleep(settings.scheduler_interval_seconds)
    return ticks
```

- [ ] **Step 4: Rewrite `src/pact/main.py` to attach the lifespan + accept `env`**

Replace the whole of `src/pact/main.py` with:

```python
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Mapping

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock, RealClock
from pact.config import load_settings
from pact.factory import build_payment_provider, build_reasoning_provider
from pact.lifecycle import reconcile_on_startup
from pact.repository import Repository
from pact.scheduler import run_ticker_loop


def build_app(env: Mapping[str, str] | None = None):
    # Read configuration from the process environment so PACT_CLOCK_MODE=demo (and the
    # other PACT_* knobs) take effect at startup. Tests inject a dict instead of os.environ.
    settings = load_settings(os.environ if env is None else env)
    repo = Repository.connect(settings.db_path)
    repo.init_schema()
    if settings.clock_mode == "demo":
        clock = FixedClock(datetime.fromisoformat(settings.demo_seed_iso))
    else:
        clock = RealClock()
    # Config-driven provider/payment selection (locked: the brain is a Hermes AGENT;
    # TestLLMProvider is only the deterministic fallback/stub).
    provider = build_reasoning_provider(settings, repo, clock)
    payment = build_payment_provider(settings)
    tokens = TokenStore()

    @asynccontextmanager
    async def lifespan(app):
        # Startup: one reconciliation sweep so a server restarted mid-pact settles
        # any active pact past its deadline and closes any elapsed dispute window.
        reconcile_on_startup(repo, clock, payment, settings)

        # Autonomous ticker: only on a real-time clock with the scheduler enabled.
        # In demo mode (FixedClock) time is driven by /demo/advance-day, so the
        # real-time ticker must NOT run.
        app.state.ticker_task = None
        app.state.ticker_stop = None
        if settings.scheduler_enabled and isinstance(clock, RealClock):
            stop = asyncio.Event()
            app.state.ticker_stop = stop
            app.state.ticker_task = asyncio.create_task(
                run_ticker_loop(repo, clock, payment, settings, stop=stop)
            )
        try:
            yield
        finally:
            # Shutdown: signal stop and cancel the background ticker if running.
            if app.state.ticker_stop is not None:
                app.state.ticker_stop.set()
            task = app.state.ticker_task
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = create_app(repo, provider, payment, tokens, clock, settings)
    # create_app's signature stays unchanged; we attach the lifespan to the built app.
    app.router.lifespan_context = lifespan
    return app


app = build_app()
```

Notes on the integration choices:
- `create_app` is called unchanged; the lifespan is attached afterward via `app.router.lifespan_context` so every existing test that imports/uses `create_app` is unaffected.
- `build_app()` keeps working with no args (reads `os.environ`); `env=` is added for tests, so the module-level `app = build_app()` line is unchanged.
- `provider`/`payment` now come from `factory.build_reasoning_provider` / `build_payment_provider` (per the frozen contract). If the factory task has not landed yet, temporarily substitute `from pact.reasoning import TestLLMProvider` + `from pact.payment import TestLinkProvider` and `provider = TestLLMProvider(); payment = TestLinkProvider()` to keep this task self-contained, then switch to the factory imports once Task (factory) lands.

- [ ] **Step 5: Run the test — expect PASS**

```bash
uv run pytest tests/test_lifespan_scheduler.py -v
```

Expected: all 5 tests pass. The ticker helper runs exactly one tick and stops (tests 1–2); startup reconciliation settles the ghosted pact (test 3); demo mode starts no ticker (test 4); real-clock mode starts then cancels the ticker (test 5).

- [ ] **Step 6: Run the full suite — expect PASS (no regressions)**

```bash
uv run pytest -q
```

Expected: the full suite stays green (254 prior tests + 5 new). `create_app` signature/behavior is unchanged, so `test_api_*`, `test_smoke`, `test_reconcile`, and `test_scheduler` are unaffected. If `pact.factory` does not yet exist, confirm Step 4's temporary substitution is in place (or run only `tests/test_lifespan_scheduler.py` until the factory task lands), so the import does not break the suite.

- [ ] **Step 7: Commit**

```bash
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' add src/pact/main.py src/pact/scheduler.py tests/test_lifespan_scheduler.py
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' commit -m "$(cat <<'EOF'
feat(main): FastAPI lifespan — startup reconciliation + autonomous ticker

Attach a lifespan in build_app: run reconcile_on_startup once on boot, and on
a RealClock with scheduler_enabled start a cancellable background asyncio task
that calls scheduler.tick every scheduler_interval_seconds. Demo/FixedClock mode
starts no real-time ticker. The loop body is factored into scheduler.run_ticker_loop
(guarded by a stop Event + injected async sleep) so it runs deterministically in
tests with no real delay. create_app stays backward-compatible.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

**Call sites updated by this task:**
- `src/pact/main.py` `build_app()` — gains an optional `env=None` parameter (backward-compatible; default reads `os.environ`). The module-level `app = build_app()` call is unchanged.
- No `create_app` call sites change — its signature is untouched, and the lifespan is attached to the constructed app object.

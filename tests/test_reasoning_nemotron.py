"""Tier 3: reasoning on NVIDIA Nemotron (via NIM).

Uses a fake OpenAI-compatible client so tests run with no SDK/network. Verifies
Nemotron handles draft/coach/verdict, that safety refusals still apply before any
model call, that anti-cheat judging stays deterministic, and that any model
failure falls back to the deterministic stub.
"""

import json
from datetime import datetime, timezone

from pact.clock import FixedClock
from pact.config import load_settings
from pact.factory import build_reasoning_provider
from pact.models import TaskType
from pact.reasoning import NemotronProvider, TestLLMProvider, make_reasoning_task

CLOCK = FixedClock(datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc))


class _FakeClient:
    """Minimal stand-in for openai.OpenAI: returns queued contents in order."""

    def __init__(self, contents):
        self._contents = list(contents)
        self.calls = []

        client = self

        class _Completions:
            def create(self, *, model, messages, **kw):
                client.calls.append({"model": model, "messages": messages})
                content = client._contents.pop(0)
                if isinstance(content, Exception):
                    raise content

                class _Msg:
                    def __init__(self, c):
                        self.message = type("M", (), {"content": c})

                return type("R", (), {"choices": [_Msg(content)]})

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def _task(ttype, inp):
    return make_reasoning_task(ttype, "pact_test", inp, CLOCK)


def _provider(contents):
    return NemotronProvider(TestLLMProvider(), client=_FakeClient(contents), model="nvidia/nemotron-test")


def test_draft_uses_nemotron_and_keeps_valid_rubric():
    out = json.dumps({"title": "Meditate daily", "goal": "Sit 10 min", "target_count": 3, "recommended_stake_cents": 6000})
    provider = _provider([out])
    result = provider.resolve(_task(TaskType.draft, {"prompt": "meditate 3 days this week"}))
    assert result["refused"] is False
    assert result["title"] == "Meditate daily"
    assert result["target_count"] == 3
    assert result["recommended_stake_cents"] == 6000
    # rubric is built deterministically and stays consistent with target_count
    assert result["rubric"]["count_target"] == 3
    assert result["rubric"]["min_distinct_days"] == 2
    assert result["rubric"]["require_token"] is True


def test_draft_refuses_unsafe_goal_without_calling_model():
    provider = _provider([])  # no model responses queued
    result = provider.resolve(_task(TaskType.draft, {"prompt": "Hurt myself if I skip a workout"}))
    assert result["refused"] is True
    assert "988" in result["reason"]
    assert provider._client.calls == []  # model never called for a refused goal


def test_draft_falls_back_to_stub_on_bad_model_json():
    provider = _provider(["not json at all"])
    result = provider.resolve(_task(TaskType.draft, {"prompt": "work out 5 times this week"}))
    assert result["refused"] is False
    # fell back to the deterministic stub draft
    assert result["target_count"] == 5


def test_coach_uses_nemotron_message():
    provider = _provider(["One session today keeps your stake. Put it on the calendar now."])
    result = provider.resolve(_task(TaskType.coach, {"valid": 2, "target": 5, "days_left": 3, "charity": "AMF"}))
    assert "calendar" in result["message"].lower()


def test_coach_falls_back_on_model_error():
    provider = _provider([RuntimeError("nim down")])
    result = provider.resolve(_task(TaskType.coach, {"valid": 2, "target": 5, "days_left": 3, "charity": "AMF"}))
    # deterministic stub message
    assert "2 of 5 done" in result["message"]


def test_verdict_uses_nemotron_summary():
    provider = _provider(["You completed 5 of 5 sessions and kept your stake."])
    result = provider.resolve(_task(TaskType.verdict, {"valid": 5, "target": 5}))
    assert "5 of 5" in result["summary"]


def test_judge_proof_stays_deterministic_no_model_call():
    provider = _provider([])
    result = provider.resolve(_task(TaskType.judge_proof, {"token_ok": True, "content_ok": True, "is_duplicate": False}))
    assert result["status"] == "passed"
    assert provider._client.calls == []  # anti-cheat never calls the model


def test_factory_uses_nemotron_fallback_when_key_set(tmp_path):
    settings = load_settings({"PACT_NEMOTRON_API_KEY": "nvapi-test", "PACT_REASONING_MODE": "hybrid"})
    # fallback defaults to NemotronProvider; inspect via a stub repo/clock
    from pact.reasoning import BrokerReasoningProvider
    provider = build_reasoning_provider(settings, repo=None, clock=CLOCK)
    assert isinstance(provider, BrokerReasoningProvider)
    assert isinstance(provider.fallback, NemotronProvider)


def test_factory_uses_plain_stub_without_key():
    settings = load_settings({"PACT_REASONING_MODE": "hybrid"})
    from pact.reasoning import BrokerReasoningProvider
    provider = build_reasoning_provider(settings, repo=None, clock=CLOCK)
    assert isinstance(provider, BrokerReasoningProvider)
    assert isinstance(provider.fallback, TestLLMProvider)
    assert not isinstance(provider.fallback, NemotronProvider)

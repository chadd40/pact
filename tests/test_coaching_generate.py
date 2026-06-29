from datetime import datetime, timezone

from pact.clock import FixedClock
from pact.coaching import generate_coach_message, user_reply
from pact.models import (
    CoachingMessage,
    Modality,
    Pact,
    PactStatus,
    Proof,
    ProofStatus,
    Rubric,
    StakeState,
)
from pact.reasoning import TestLLMProvider


def _rubric() -> Rubric:
    return Rubric(
        modality=Modality.photo,
        require_token=True,
        must_show=["clear evidence the action was performed"],
        reject_if=["stock/watermark", "missing token"],
        min_distinct_days=5,
        count_target=5,
        rest_if_injured_counts=True,
        rigor_floor={
            "require_token": True,
            "min_distinct_days": 4,
            "non_negotiable": ["require_token", "server_time_is_truth", "no_duplicates"],
        },
    )


def _pact(clock: FixedClock) -> Pact:
    now = clock.now()
    return Pact(
        id="pact_coach1",
        owner="demo@pact.local",
        original_prompt="work out 5x this week or $20 to charity",
        title="Work out 5x this week",
        goal="Complete 5 workout sessions on 5 distinct days this week.",
        timezone="America/Los_Angeles",
        deadline_at=datetime(2026, 6, 24, 9, 0, 0, tzinfo=timezone.utc),
        target_count=5,
        recommended_stake_cents=2000,
        stake_amount_cents=2000,
        charity_id="against_malaria_foundation",
        charity_url="https://againstmalaria.com/donate",
        rubric=_rubric(),
        status=PactStatus.active,
        stake_state=StakeState.committed,
        created_at=now,
        started_at=now,
    )


def _proof(pact_id: str, bucket: str, when: datetime) -> Proof:
    return Proof(
        id=f"proof_{bucket}",
        pact_id=pact_id,
        modality=Modality.photo,
        received_at=when,
        day_bucket=bucket,
        token_issued="PACT-7Q",
        token_ok=True,
        status=ProofStatus.passed,
        judge_reason="Token verified; content satisfies rubric; no duplicate.",
        judge_checklist={"token": True, "content": True, "not_dup": True},
    )


def test_generate_coach_message_outbound_with_snapshot() -> None:
    clock = FixedClock(datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc))
    pact = _pact(clock)
    proofs = [
        _proof(pact.id, "2026-06-20", datetime(2026, 6, 20, 9, 0, 0, tzinfo=timezone.utc)),
        _proof(pact.id, "2026-06-21", datetime(2026, 6, 21, 9, 0, 0, tzinfo=timezone.utc)),
    ]
    provider = TestLLMProvider()

    msg = generate_coach_message(
        pact, proofs, "mid_week", provider, clock, "World Central Kitchen"
    )

    assert isinstance(msg, CoachingMessage)
    assert msg.pact_id == pact.id
    assert msg.direction == "outbound"
    assert msg.trigger == "mid_week"
    assert msg.channel == "web"
    assert msg.body.strip() != ""
    assert msg.sent_at == clock.now()
    assert msg.id != ""
    snap = msg.pact_state_snapshot
    assert snap["valid"] == 2
    assert snap["target"] == 5
    assert snap["days_left"] == 2
    assert "World Central Kitchen" in msg.body


def test_generate_coach_message_id_is_deterministic() -> None:
    clock = FixedClock(datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc))
    pact = _pact(clock)
    provider = TestLLMProvider()

    a = generate_coach_message(pact, [], "mid_week", provider, clock, "World Central Kitchen")
    b = generate_coach_message(pact, [], "mid_week", provider, clock, "World Central Kitchen")
    assert a.id == b.id


def test_user_reply_returns_inbound_then_outbound() -> None:
    clock = FixedClock(datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc))
    pact = _pact(clock)
    provider = TestLLMProvider()

    inbound, outbound = user_reply(pact, "I will do two sessions tomorrow", [], provider, clock)

    assert isinstance(inbound, CoachingMessage)
    assert isinstance(outbound, CoachingMessage)
    assert inbound.pact_id == pact.id
    assert outbound.pact_id == pact.id

    assert inbound.direction == "inbound"
    assert inbound.trigger == "reply"
    assert inbound.body == "I will do two sessions tomorrow"
    assert inbound.sent_at == clock.now()

    assert outbound.direction == "outbound"
    assert outbound.trigger == "reply"
    assert outbound.body.strip() != ""
    assert outbound.sent_at == clock.now()

    assert inbound.id != outbound.id


def test_user_reply_gives_provider_the_user_message_and_pact_context() -> None:
    clock = FixedClock(datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc))
    pact = _pact(clock)
    provider = CapturingCoachProvider()

    _inbound, outbound = user_reply(
        pact,
        "Should I do the next workout before breakfast?",
        [],
        provider,
        clock,
    )

    assert provider.input["user_message"] == "Should I do the next workout before breakfast?"
    assert provider.input["title"] == "Work out 5x this week"
    assert provider.input["goal"] == "Complete 5 workout sessions on 5 distinct days this week."
    assert provider.input["stake_cents"] == 2000
    assert outbound.body == "context-aware reply"


def test_user_reply_answers_screenshot_proof_questions_without_generic_fallback() -> None:
    clock = FixedClock(datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc))
    pact = _pact(clock)
    provider = TestLLMProvider()

    _inbound, outbound = user_reply(
        pact,
        "I only have a screenshot from today's workout. Is that enough?",
        [],
        provider,
        clock,
    )

    assert "screenshot" in outbound.body.lower()
    assert "proof" in outbound.body.lower()
    assert "Work out 5x this week" in outbound.body
    assert "Pick the next visible rep" not in outbound.body


class CapturingCoachProvider:
    def __init__(self) -> None:
        self.input: dict = {}

    def capabilities(self) -> set[str]:
        return {"text"}

    def resolve(self, task) -> dict:
        self.input = dict(task.input)
        return {"message": "context-aware reply"}

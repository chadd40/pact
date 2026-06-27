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
        owner="demo@pact.local",
        original_prompt="work out 5x this week or $20 to charity",
        title="Work out 5x this week",
        goal="Complete 5 workout sessions on 5 distinct days this week.",
        timezone="America/Los_Angeles",
        deadline_at=_utc(2026, 6, 29, 6, 59, 59),
        target_count=5,
        recommended_stake_cents=2000,
        stake_amount_cents=2000,
        charity_id="against_malaria_foundation",
        charity_url="https://againstmalaria.com/donate",
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

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
        charity_id="against_malaria_foundation",
        charity_url="https://againstmalaria.com/donate",
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

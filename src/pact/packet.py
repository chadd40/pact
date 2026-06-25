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

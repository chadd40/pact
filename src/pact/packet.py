from datetime import datetime, timezone

from .models import DonationReceipt, PactStatus, Pact, Proof, Verdict


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


def _iso_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _receipt_block(verdict: Verdict, receipt: DonationReceipt | None) -> dict:
    if receipt is not None:
        return {
            "receipt_status": receipt.receipt_status,
            "receipt_source": receipt.receipt_source,
            "receipt_ref": receipt.receipt_ref,
            "receipt_url": receipt.receipt_url,
            "receipt_artifact_path": receipt.receipt_artifact_path,
            "confirmed_at": _iso_z(receipt.confirmed_at),
        }
    if verdict.payment_ref is not None:
        return {
            "receipt_status": "unconfirmed",
            "receipt_source": None,
            "receipt_ref": None,
            "receipt_url": None,
            "receipt_artifact_path": verdict.receipt_artifact_path,
            "confirmed_at": None,
        }
    return {
        "receipt_status": "not_required",
        "receipt_source": None,
        "receipt_ref": None,
        "receipt_url": None,
        "receipt_artifact_path": None,
        "confirmed_at": None,
    }


def build_packet(
    pact: Pact,
    proofs: list[Proof],
    verdict: Verdict,
    receipt: DonationReceipt | None = None,
) -> dict:
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
    verdict_block.update(_receipt_block(verdict, receipt))

    return {
        "pact": pact.model_dump(mode="json"),
        "proofs": [_proof_row(p) for p in proofs],
        "verdict": verdict_block,
        "honesty_note": verdict.honesty_note,
    }

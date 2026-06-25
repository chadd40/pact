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

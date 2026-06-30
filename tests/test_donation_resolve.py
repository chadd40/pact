"""Task 5: Link-confirmed resolution -> donation_complete."""
from datetime import datetime, timezone

from pact.clock import FixedClock
from pact.lifecycle import finalize_donation, resolve_via_link
from pact.models import DonationReceipt, Modality, Pact, PactStatus, Rubric, StakeState
from pact.payment import PaymentStatus, payment_status_is_captured


def _clock() -> FixedClock:
    return FixedClock(datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc))


def _pact(status=PactStatus.donation_pending, spend_request_id="lsrq_x") -> Pact:
    return Pact(
        id="pact_resolve", owner="demo@pact.local", original_prompt="x", title="t", goal="g",
        timezone="America/Los_Angeles", deadline_at=datetime(2026, 6, 28, 23, 59, 59, tzinfo=timezone.utc),
        target_count=5, recommended_stake_cents=2000, stake_amount_cents=2000,
        charity_id="against_malaria_foundation", charity_url="https://againstmalaria.com/donate",
        rubric=Rubric(modality=Modality.photo, must_show=["x"], min_distinct_days=5, count_target=5),
        status=status, stake_state=StakeState.committed, spend_request_id=spend_request_id,
        created_at=datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc),
    )


class _LinkStatusProvider:
    def __init__(self, status):
        self._status = status

    def get_donation_status(self, pact):
        return PaymentStatus(provider="link_cli", status=self._status,
                             provider_ref=pact.spend_request_id, payload={})


def test_captured_status_excludes_mere_approval():
    # "approved"/"issued" = the card was issued at creation, NOT charged at the charity.
    assert payment_status_is_captured("completed")
    assert payment_status_is_captured("captured")
    assert payment_status_is_captured("succeeded")  # dry-run/test simulation
    assert not payment_status_is_captured("approved")
    assert not payment_status_is_captured("pending_approval")
    assert not payment_status_is_captured("created")


def test_resolve_via_link_confirms_and_completes():
    pact = _pact(status=PactStatus.donation_pending)
    pact, receipt = resolve_via_link(pact, _LinkStatusProvider("completed"), _clock())
    assert pact.status == PactStatus.donation_complete
    assert pact.stake_state == StakeState.executed
    assert receipt is not None
    assert receipt.receipt_status == "provider_confirmed"
    assert receipt.receipt_source == "link"
    assert receipt.receipt_ref == "lsrq_x"
    assert "completed" in receipt.confirmation_notes


def test_resolve_via_link_not_yet_captured_stays_donated():
    pact = _pact(status=PactStatus.donation_pending)
    pact, receipt = resolve_via_link(pact, _LinkStatusProvider("pending_approval"), _clock())
    assert pact.status == PactStatus.donated  # interim: submitted, awaiting Link confirmation
    assert receipt is None


def test_finalize_donation_completes_on_confirming_receipt():
    pact = _pact(status=PactStatus.donated)
    r = DonationReceipt(pact_id=pact.id, receipt_status="manual_receipt", receipt_ref="AMF-1")
    out = finalize_donation(pact, r)
    assert out.status == PactStatus.donation_complete
    assert out.stake_state == StakeState.executed


def test_finalize_donation_ignores_non_confirming_receipt():
    pact = _pact(status=PactStatus.donated)
    r = DonationReceipt(pact_id=pact.id, receipt_status="failed_or_reversed")
    out = finalize_donation(pact, r)
    assert out.status == PactStatus.donated  # not completed

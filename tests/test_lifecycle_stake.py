"""Task 2: stake pre-authorization at pact creation.

confirm_and_start opens the Link spend-request and, when the card is immediately
available (dry-run/test), provisions it and goes active. In live mode the card is
not available until the human approves in Link, so the pact parks at awaiting_stake
with the approval URL; confirm_stake later picks up the approved card.
"""
from datetime import datetime, timezone

from pact.clock import FixedClock
from pact.config import Settings
from pact.lifecycle import confirm_and_start, confirm_stake
from pact.models import Modality, Pact, PactStatus, Rubric
from pact.payment import CardCredential, PaymentResult, TestLinkProvider


def _clock() -> FixedClock:
    return FixedClock(datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc))


def _draft() -> Pact:
    return Pact(
        id="pact_stake",
        owner="demo@pact.local",
        original_prompt="work out 5x this week or $20 to charity",
        title="Work out 5x this week",
        goal="Complete 5 workout sessions on 5 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=datetime(2026, 6, 28, 23, 59, 59, tzinfo=timezone.utc),
        target_count=5,
        recommended_stake_cents=2000,
        stake_amount_cents=2000,
        charity_id="against_malaria_foundation",
        charity_url="https://againstmalaria.com/donate",
        rubric=Rubric(modality=Modality.photo, must_show=["x"], min_distinct_days=5, count_target=5),
        created_at=datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc),
    )


class _PendingApprovalProvider:
    """Live-like: create opens a spend-request; the card is unavailable until approved."""

    provider = "link_cli"

    def __init__(self) -> None:
        self.approved = False

    def create_donation(self, pact, idempotency_key):
        return PaymentResult(
            provider="link_cli",
            status="pending_approval",
            provider_ref="lsrq_pending",
            payload={"mode": "live", "link_cli": {"approval_url": "https://link/approve/xyz"}},
        )

    def retrieve_card(self, provider_ref, *, output_dir):
        if not self.approved:
            raise RuntimeError("link-cli returned no card; the spend request is not approved yet")
        return CardCredential(
            provider="link_cli", spend_request_id=provider_ref,
            card_file=f"{output_dir}/card_{provider_ref}.json", last4="8855", brand="visa",
            exp_month=8, exp_year=2028, mode="live",
        )


def test_confirm_and_start_dryrun_provider_goes_active_with_card(tmp_path):
    pact = confirm_and_start(
        _draft(), 2000, "against_malaria_foundation", _clock(), Settings(),
        consent_acknowledged=True, payment=TestLinkProvider(), artifacts_dir=str(tmp_path),
    )
    assert pact.status == PactStatus.active
    assert pact.spend_request_id
    assert pact.card_last4 == "4242"
    assert pact.card_artifact_path


def test_confirm_and_start_live_pending_goes_awaiting_stake(tmp_path):
    prov = _PendingApprovalProvider()
    pact = confirm_and_start(
        _draft(), 2000, "against_malaria_foundation", _clock(), Settings(),
        consent_acknowledged=True, payment=prov, artifacts_dir=str(tmp_path),
    )
    assert pact.status == PactStatus.awaiting_stake
    assert pact.spend_request_id == "lsrq_pending"
    assert pact.stake_approval_url == "https://link/approve/xyz"
    assert pact.card_last4 is None


def test_confirm_stake_after_approval_goes_active(tmp_path):
    prov = _PendingApprovalProvider()
    pact = confirm_and_start(
        _draft(), 2000, "against_malaria_foundation", _clock(), Settings(),
        consent_acknowledged=True, payment=prov, artifacts_dir=str(tmp_path),
    )
    assert pact.status == PactStatus.awaiting_stake
    prov.approved = True
    pact = confirm_stake(pact, prov, _clock(), Settings(), artifacts_dir=str(tmp_path))
    assert pact.status == PactStatus.active
    assert pact.card_last4 == "8855"
    assert pact.stake_approval_url is None


def test_confirm_and_start_without_payment_is_active_unchanged():
    pact = confirm_and_start(
        _draft(), 2000, "against_malaria_foundation", _clock(), Settings(),
        consent_acknowledged=True,
    )
    assert pact.status == PactStatus.active
    assert pact.spend_request_id is None

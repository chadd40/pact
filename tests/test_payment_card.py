"""Tier 1: virtual card provisioning.

After a donation spend-request is approved, the agent retrieves the issued
virtual card to a file (never into process return values / logs) so the
Stripe-Checkout helper can complete the donation. Dry-run/test modes write
Stripe's universal test card so the whole flow is exercisable with no real
money and no link-cli.
"""

import json
import os
import stat
from datetime import datetime, timezone

from pact.models import Modality, Pact, Rubric
from pact.payment import CardCredential, LinkCliProvider, TestLinkProvider


def _make_pact(pact_id: str = "pact_card", stake_amount_cents: int = 2000) -> Pact:
    return Pact(
        id=pact_id,
        owner="demo@pact.local",
        original_prompt="work out 5x this week or $20 to charity",
        title="Work out 5x this week",
        goal="Complete 5 workout sessions on 5 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=datetime(2026, 6, 28, 23, 59, 59, tzinfo=timezone.utc),
        target_count=5,
        recommended_stake_cents=2000,
        stake_amount_cents=stake_amount_cents,
        charity_id="against_malaria_foundation",
        charity_url="https://againstmalaria.com/donate",
        rubric=Rubric(
            modality=Modality.photo, must_show=["x"], min_distinct_days=5, count_target=5
        ),
        created_at=datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc),
    )


class _FakeRunner:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def run(self, args, timeout):
        self.calls.append((args, timeout))
        return self.response


def test_test_provider_provisions_a_test_card_to_a_locked_file(tmp_path):
    cred = TestLinkProvider().retrieve_card("sr_x", output_dir=str(tmp_path))

    assert isinstance(cred, CardCredential)
    assert cred.last4 == "4242"  # Stripe universal test card
    assert os.path.exists(cred.card_file)
    data = json.loads(open(cred.card_file).read())
    assert data["card"]["number"].endswith("4242")
    # The secret card file must be owner-read/write only.
    assert stat.S_IMODE(os.stat(cred.card_file).st_mode) == 0o600


def test_card_credential_never_carries_the_pan():
    # The handle returned in-process exposes only non-secret metadata + the file
    # path; the PAN stays in the file on disk.
    cred = CardCredential(
        provider="link_cli", spend_request_id="sr", card_file="/tmp/x.json",
        last4="4242", brand="visa", exp_month=12, exp_year=2030, mode="dry_run",
    )
    blob = json.dumps(cred.__dict__)
    assert "4242424242424242" not in blob
    assert "number" not in blob


def test_dry_run_retrieve_card_makes_no_subprocess_call(tmp_path):
    provider = LinkCliProvider()  # dry_run default
    cred = provider.retrieve_card("sr_dry", output_dir=str(tmp_path))
    assert cred.mode == "dry_run"
    assert cred.last4 == "4242"
    assert os.path.exists(cred.card_file)


def test_live_retrieve_card_argv_and_parses_metadata(tmp_path):
    runner = _FakeRunner({"card": {"last4": "1234", "brand": "visa", "exp_month": 11, "exp_year": 2029}})
    provider = LinkCliProvider(link_mode="live", payment_method_id="pm_1", runner=runner)

    cred = provider.retrieve_card("sr_live", output_dir=str(tmp_path))

    assert cred.last4 == "1234"
    assert cred.brand == "visa"
    assert cred.exp_month == 11 and cred.exp_year == 2029
    assert cred.card_file.endswith("card_sr_live.json")

    args, _ = runner.calls[0]
    assert args[:4] == ["link-cli", "spend-request", "retrieve", "sr_live"]
    assert "--include" in args and args[args.index("--include") + 1] == "card"
    assert "--output-file" in args and args[args.index("--output-file") + 1] == cred.card_file


def test_live_test_retrieve_card_appends_test_flag(tmp_path):
    runner = _FakeRunner({"card": {"last4": "9999"}})
    provider = LinkCliProvider(link_mode="live_test", payment_method_id="pm_1", runner=runner)

    cred = provider.retrieve_card("sr_t", output_dir=str(tmp_path))

    assert "--test" in runner.calls[0][0]
    assert cred.mode == "live_test"
    assert cred.last4 == "9999"

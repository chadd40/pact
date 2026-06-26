from datetime import datetime, timezone

import pytest

import pact.payment as payment_mod
from pact.config import Settings, load_settings
from pact.models import Modality, Pact, Rubric
from pact.payment import (
    LinkCliProvider,
    PaymentResult,
    TestLinkProvider,
    get_payment_provider,
)


def _make_pact(
    pact_id: str = "pact_abc123",
    stake_amount_cents: int = 2000,
    charity_id: str = "world_central_kitchen",
) -> Pact:
    created = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    rubric = Rubric(
        modality=Modality.photo,
        must_show=["person mid/post exercise"],
        min_distinct_days=5,
        count_target=5,
    )
    return Pact(
        id=pact_id,
        owner="colehaddad40@gmail.com",
        original_prompt="work out 5x this week or $20 to charity",
        title="Work out 5x this week",
        goal="Complete 5 workout sessions on 5 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=datetime(2026, 6, 28, 23, 59, 59, tzinfo=timezone.utc),
        target_count=5,
        recommended_stake_cents=2000,
        stake_amount_cents=stake_amount_cents,
        charity_id=charity_id,
        charity_url="https://wck.org/donate",
        rubric=rubric,
        created_at=created,
    )


def test_dry_run_is_the_default_link_mode():
    s = Settings()
    assert s.link_mode == "dry_run"


def test_link_mode_env_override_to_live():
    s = load_settings({"PACT_LINK_MODE": "live"})
    assert s.link_mode == "live"
    # other fields untouched
    assert s.payment_mode == "test_link"


def test_dry_run_create_donation_shape():
    provider = LinkCliProvider()  # defaults to dry_run
    pact = _make_pact(pact_id="pact_abc123", stake_amount_cents=2000)

    result = provider.create_donation(pact, idempotency_key="pact_abc123:donation")

    assert isinstance(result, PaymentResult)
    assert result.provider == "link_cli"
    assert result.status == "dry_run"
    assert result.provider_ref == "dryrun_sr_pact_abc123_2000"


def test_dry_run_payload_marks_mode_and_note():
    provider = LinkCliProvider()
    pact = _make_pact(
        pact_id="pact_abc123",
        stake_amount_cents=2000,
        charity_id="world_central_kitchen",
    )

    result = provider.create_donation(pact, idempotency_key="pact_abc123:donation")

    assert result.payload["mode"] == "dry_run"
    assert result.payload["note"] == "no real link-cli call"
    assert result.payload["charity_id"] == "world_central_kitchen"
    assert result.payload["amount_cents"] == 2000
    assert result.payload["idempotency_key"] == "pact_abc123:donation"


def test_dry_run_makes_no_subprocess_call(monkeypatch):
    def _tripwire(*args, **kwargs):
        raise AssertionError(
            "LinkCliProvider dry-run must NOT shell out (no real money/link-cli)"
        )

    # If LinkCliProvider ever reaches for subprocess in dry-run, fail loudly.
    monkeypatch.setattr(payment_mod, "subprocess", _DummySubprocess(_tripwire))

    provider = LinkCliProvider()
    pact = _make_pact()

    result = provider.create_donation(pact, idempotency_key="pact_abc123:donation")

    assert result.status == "dry_run"


class _DummySubprocess:
    """Stand-in for the subprocess module whose run() trips the test."""

    def __init__(self, run_fn):
        self.run = run_fn


def test_dry_run_provider_ref_is_deterministic():
    provider = LinkCliProvider()
    pact = _make_pact(pact_id="pact_xyz", stake_amount_cents=500)

    first = provider.create_donation(pact, idempotency_key="pact_xyz:donation")
    second = provider.create_donation(pact, idempotency_key="pact_xyz:donation")

    assert first.provider_ref == "dryrun_sr_pact_xyz_500"
    assert first.provider_ref == second.provider_ref


def test_get_payment_provider_defaults_to_test_link():
    s = Settings()  # payment_mode == "test_link"
    provider = get_payment_provider(s)
    assert isinstance(provider, TestLinkProvider)


def test_get_payment_provider_selects_link_cli():
    s = load_settings({"PACT_PAYMENT_MODE": "link_cli"})
    provider = get_payment_provider(s)
    assert isinstance(provider, LinkCliProvider)
    # carries the configured link_mode (dry_run by default — safe)
    assert provider.link_mode == "dry_run"

import subprocess
from datetime import datetime, timezone

import pytest

import pact.payment as payment_mod
from pact.config import Settings, load_settings
from pact.models import Modality, Pact, Rubric
from pact.payment import (
    LinkChargeAmbiguous,
    LinkCliProvider,
    PaymentResult,
    SubprocessLinkCliRunner,
    TestLinkProvider,
    get_payment_provider,
)


def _make_pact(
    pact_id: str = "pact_abc123",
    stake_amount_cents: int = 2000,
    charity_id: str = "against_malaria_foundation",
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
        owner="demo@pact.local",
        original_prompt="work out 5x this week or $20 to charity",
        title="Work out 5x this week",
        goal="Complete 5 workout sessions on 5 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=datetime(2026, 6, 28, 23, 59, 59, tzinfo=timezone.utc),
        target_count=5,
        recommended_stake_cents=2000,
        stake_amount_cents=stake_amount_cents,
        charity_id=charity_id,
        charity_url="https://againstmalaria.com/donate",
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
        charity_id="against_malaria_foundation",
    )

    result = provider.create_donation(pact, idempotency_key="pact_abc123:donation")

    assert result.payload["mode"] == "dry_run"
    assert result.payload["note"] == "no real link-cli call"
    assert result.payload["charity_id"] == "against_malaria_foundation"
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


class _FakeRunner:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def run(self, args, timeout):
        self.calls.append((args, timeout))
        return self.response


def test_live_mode_creates_link_cli_spend_request_with_human_approval_context():
    runner = _FakeRunner({"id": "sr_live_123", "status": "pending_approval"})
    provider = LinkCliProvider(
        link_mode="live",
        payment_method_id="pm_123",
        runner=runner,
    )
    pact = _make_pact(
        pact_id="pact_live",
        stake_amount_cents=2000,
        charity_id="against_malaria_foundation",
    )

    result = provider.create_donation(pact, idempotency_key="pact_live:donation")

    assert result.provider == "link_cli"
    # Non-blocking: create opens the request awaiting the human's Link approval; it
    # does NOT capture inline. Money only moves once /approve sees it approved.
    assert result.status == "pending_approval"
    assert result.provider_ref == "sr_live_123"
    assert result.payload["mode"] == "live"
    assert result.payload["idempotency_key"] == "pact_live:donation"

    args, timeout = runner.calls[0]
    assert timeout == 600
    assert args[:4] == ["link-cli", "spend-request", "create", "--format"]
    # The create must NOT poll/capture — approval is requested as a separate step.
    assert "--no-request-approval" in args
    assert "--payment-method-id" in args
    assert args[args.index("--payment-method-id") + 1] == "pm_123"
    assert "--amount" in args
    assert args[args.index("--amount") + 1] == "2000"
    assert "--merchant-name" in args
    assert args[args.index("--merchant-name") + 1] == "Against Malaria Foundation"
    assert "--merchant-url" in args
    assert args[args.index("--merchant-url") + 1] == "https://www.againstmalaria.com/donation.aspx"
    context = args[args.index("--context") + 1]
    assert "Pact failed" in context
    assert "pact_live" in context
    assert len(context) >= 100


def test_live_create_is_non_blocking_then_requests_approval():
    runner = _FakeRunner({"id": "sr1", "status": "pending_approval"})
    provider = LinkCliProvider(link_mode="live", payment_method_id="pm_123", runner=runner)
    pact = _make_pact(pact_id="pact_live")

    result = provider.create_donation(pact, idempotency_key="pact_live:donation")

    assert result.provider_ref == "sr1"
    assert result.status == "pending_approval"
    # Two subprocess calls: non-blocking create, then a separate request-approval.
    assert len(runner.calls) == 2
    create_args = runner.calls[0][0]
    assert create_args[2] == "create"
    assert "--no-request-approval" in create_args
    approval_args = runner.calls[1][0]
    assert approval_args[:3] == ["link-cli", "spend-request", "request-approval"]
    assert approval_args[3] == "sr1"


def test_request_approval_failure_is_non_fatal_and_keeps_the_ref():
    class _CreateOkApprovalBoom:
        def __init__(self):
            self.calls = []

        def run(self, args, timeout):
            self.calls.append(args)
            if args[2] == "request-approval":
                raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)
            return {"id": "sr_keep", "status": "open"}

    provider = LinkCliProvider(
        link_mode="live", payment_method_id="pm_123", runner=_CreateOkApprovalBoom()
    )
    pact = _make_pact(pact_id="pact_keep")

    # A failed approval request must not lose the created spend request; the ref is
    # persisted so the user can be re-prompted rather than double-charged.
    result = provider.create_donation(pact, idempotency_key="pact_keep:donation")
    assert result.provider_ref == "sr_keep"


def test_create_subprocess_failure_raises_link_charge_ambiguous():
    class _BoomRunner:
        def run(self, args, timeout):
            raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)

    provider = LinkCliProvider(
        link_mode="live", payment_method_id="pm_123", runner=_BoomRunner()
    )
    pact = _make_pact()

    # The create subprocess fired but the outcome is unknown — must surface as an
    # ambiguous charge (caller parks for reconcile), NOT a clean failure.
    with pytest.raises(LinkChargeAmbiguous):
        provider.create_donation(pact, idempotency_key="k")


def test_live_test_mode_shells_with_test_flag():
    runner = _FakeRunner({"id": "sr_t", "status": "pending_approval"})
    provider = LinkCliProvider(
        link_mode="live_test", payment_method_id="pm_123", runner=runner
    )
    pact = _make_pact(pact_id="pact_t")

    result = provider.create_donation(pact, idempotency_key="pact_t:donation")

    assert result.provider_ref == "sr_t"
    assert result.payload["mode"] == "live_test"
    create_args = runner.calls[0][0]
    assert "--test" in create_args  # real subprocess path, test credentials, no real money


def test_link_mode_env_override_to_live_test():
    s = load_settings({"PACT_LINK_MODE": "live_test"})
    assert s.link_mode == "live_test"


def test_subprocess_runner_surfaces_stderr_on_nonzero_exit():
    runner = SubprocessLinkCliRunner()
    with pytest.raises(RuntimeError) as exc:
        runner.run(["sh", "-c", "echo boom 1>&2; exit 7"], timeout=10)
    assert "boom" in str(exc.value)


def test_live_mode_requires_payment_method_id_before_shelling():
    runner = _FakeRunner({"id": "sr_live_123", "status": "approved"})
    provider = LinkCliProvider(link_mode="live", runner=runner)
    pact = _make_pact(pact_id="pact_live")

    with pytest.raises(RuntimeError, match="payment method"):
        provider.create_donation(pact, idempotency_key="pact_live:donation")

    assert runner.calls == []


def test_live_mode_retrieves_spend_request_status_once():
    runner = _FakeRunner({"id": "sr_live_123", "status": "pending_approval"})
    provider = LinkCliProvider(
        link_mode="live",
        payment_method_id="pm_123",
        runner=runner,
    )

    status = provider.get_donation_status("sr_live_123")

    assert status.provider == "link_cli"
    assert status.provider_ref == "sr_live_123"
    assert status.status == "pending_approval"
    assert runner.calls == [
        (
            [
                "link-cli",
                "spend-request",
                "retrieve",
                "sr_live_123",
                "--format",
                "json",
                "--timeout",
                "1",
                "--interval",
                "0",
                "--max-attempts",
                "1",
            ],
            30,
        )
    ]


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

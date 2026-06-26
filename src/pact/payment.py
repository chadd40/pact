import subprocess
from dataclasses import dataclass
from typing import Protocol

from pact.config import Settings
from pact.models import Pact


@dataclass(frozen=True)
class PaymentResult:
    provider: str
    status: str
    provider_ref: str
    payload: dict


class PaymentProvider(Protocol):
    def create_donation(self, pact: Pact, idempotency_key: str) -> PaymentResult:
        ...


class TestLinkProvider:
    """Deterministic, recording-safe payment provider. No network calls."""

    def create_donation(self, pact: Pact, idempotency_key: str) -> PaymentResult:
        return PaymentResult(
            provider="test_link",
            status="succeeded",
            provider_ref=f"test_sr_{pact.id}_{pact.stake_amount_cents}",
            payload={
                "charity_id": pact.charity_id,
                "amount_cents": pact.stake_amount_cents,
                "idempotency_key": idempotency_key,
                "mode": "test",
            },
        )


class LinkCliProvider:
    """Link-CLI payment provider.

    Dry-run (default, ``link_mode == "dry_run"``) is fully self-contained: it
    returns a clearly-marked PaymentResult and shells NOTHING — no subprocess,
    no `link-cli`, no real money. This is the only path tests exercise.

    Live mode (``link_mode == "live"``) is documented but intentionally NOT
    covered by tests and NOT auto-executed. A live run would:
      1. shell ``link-cli spend-request create`` to open a spend request,
      2. shell ``link-cli spend-request request-approval`` for the request, and
      3. require an EXPLICIT HUMAN STEP: the virtual-card -> charity-page browser
         checkout is performed by a person, never automated here.
    The ``subprocess`` import exists for that documented live path only.
    """

    provider = "link_cli"

    def __init__(self, link_mode: str = "dry_run"):
        self.link_mode = link_mode

    def create_donation(self, pact: Pact, idempotency_key: str) -> PaymentResult:
        if self.link_mode != "dry_run":
            # Live path is gated and NOT exercised by tests. It would shell
            # `link-cli spend-request create` + `request-approval` (via the
            # module-level `subprocess`) and then hand off to a human for the
            # virtual-card -> charity-page browser checkout. We refuse to run it
            # automatically so no money moves without explicit human action.
            raise RuntimeError(
                "LinkCliProvider live mode is not auto-executable; "
                "the virtual-card -> charity checkout requires explicit human action."
            )
        # Dry-run: clearly-marked, deterministic, no network, no subprocess.
        return PaymentResult(
            provider="link_cli",
            status="dry_run",
            provider_ref=f"dryrun_sr_{pact.id}_{pact.stake_amount_cents}",
            payload={
                "charity_id": pact.charity_id,
                "amount_cents": pact.stake_amount_cents,
                "idempotency_key": idempotency_key,
                "mode": "dry_run",
                "note": "no real link-cli call",
            },
        )


def get_payment_provider(settings: Settings) -> PaymentProvider:
    """Select the payment provider from Settings.

    Defaults to the recording-safe ``TestLinkProvider``; returns a (still safe,
    dry-run-by-default) ``LinkCliProvider`` only when ``payment_mode == "link_cli"``.
    """
    if settings.payment_mode == "link_cli":
        return LinkCliProvider(link_mode=settings.link_mode)
    return TestLinkProvider()

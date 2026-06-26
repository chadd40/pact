from dataclasses import dataclass
from typing import Protocol

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

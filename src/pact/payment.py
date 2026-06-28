import subprocess
import json
from dataclasses import dataclass
from hashlib import sha1
from typing import Protocol, runtime_checkable

from pact.config import Settings
from pact.charities import get_charity
from pact.models import Pact, PaymentAttempt


@dataclass(frozen=True)
class PaymentResult:
    provider: str
    status: str
    provider_ref: str
    payload: dict


@dataclass(frozen=True)
class PaymentStatus:
    provider: str
    status: str
    provider_ref: str
    payload: dict


_APPROVED_STATUSES = {
    "approved",
    "credential_issued",
    "credentialissued",
    "issued",
    "completed",
    "succeeded",
    "success",
}
_DENIED_STATUSES = {"denied", "declined", "rejected", "canceled", "cancelled"}
_EXPIRED_STATUSES = {"expired", "timed_out", "timeout", "polling_timeout"}


def _normalized_status(status: str | None) -> str:
    return (status or "").strip().lower().replace(" ", "_").replace("-", "_")


def payment_status_is_approved(status: str | None) -> bool:
    return _normalized_status(status) in _APPROVED_STATUSES


def payment_status_is_denied(status: str | None) -> bool:
    return _normalized_status(status) in _DENIED_STATUSES


def payment_status_is_expired(status: str | None) -> bool:
    return _normalized_status(status) in _EXPIRED_STATUSES


def _extract_provider_ref(payload: dict) -> str | None:
    return (
        payload.get("id")
        or payload.get("spend_request_id")
        or payload.get("spendRequestId")
    )


def _extract_status(payload: dict) -> str:
    nested = payload.get("spend_request") or payload.get("spendRequest") or {}
    approval = payload.get("approval") or {}
    raw = (
        payload.get("status")
        or payload.get("approval_status")
        or payload.get("approvalStatus")
        or (approval.get("status") if isinstance(approval, dict) else None)
        or (nested.get("status") if isinstance(nested, dict) else None)
        or "unknown"
    )
    return str(raw)


@runtime_checkable
class PaymentProvider(Protocol):
    def create_donation(self, pact: Pact, idempotency_key: str) -> PaymentResult:
        ...


class LinkCliRunner(Protocol):
    def run(self, args: list[str], timeout: int) -> dict:
        ...


class SubprocessLinkCliRunner:
    def run(self, args: list[str], timeout: int) -> dict:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
        return json.loads(completed.stdout or "{}")


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


class RecordingPaymentProvider:
    """Wrap any payment provider and persist one audit row per idempotency key."""

    def __init__(self, inner: PaymentProvider, repo, clock, settings: Settings) -> None:
        self.inner = inner
        self.repo = repo
        self.clock = clock
        self.settings = settings

    def _attempt_id(self, idempotency_key: str) -> str:
        return "pay_" + sha1(idempotency_key.encode("utf-8")).hexdigest()[:10]

    def _base_attempt(self, pact: Pact, idempotency_key: str, status: str) -> PaymentAttempt:
        charity = get_charity(pact.charity_id)
        now = self.clock.now()
        return PaymentAttempt(
            id=self._attempt_id(idempotency_key),
            pact_id=pact.id,
            owner=pact.owner,
            provider=getattr(self.inner, "provider", self.settings.payment_mode),
            mode=self.settings.link_mode if self.settings.payment_mode == "link_cli" else "test",
            status=status,
            amount_cents=pact.stake_amount_cents,
            currency=pact.currency,
            charity_id=pact.charity_id,
            merchant_name=charity["name"] if charity else pact.charity_id,
            merchant_url=charity["donation_url"] if charity else pact.charity_url,
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
        )

    def create_donation(self, pact: Pact, idempotency_key: str) -> PaymentResult:
        attempt = self._base_attempt(pact, idempotency_key, "started")
        self.repo.save_payment_attempt(attempt)
        try:
            result = self.inner.create_donation(pact, idempotency_key)
        except Exception as exc:
            failed = attempt.model_copy(
                update={
                    "status": "error",
                    "updated_at": self.clock.now(),
                    "error": str(exc),
                }
            )
            self.repo.save_payment_attempt(failed)
            raise
        saved = attempt.model_copy(
            update={
                "provider": result.provider,
                "mode": str(result.payload.get("mode", attempt.mode)),
                "status": result.status,
                "provider_ref": result.provider_ref,
                "approval_status": result.payload.get("approval_status"),
                "updated_at": self.clock.now(),
            }
        )
        self.repo.save_payment_attempt(saved)
        return result

    def get_donation_status(self, pact: Pact) -> PaymentStatus:
        provider_ref = pact.spend_request_id
        if not provider_ref:
            return PaymentStatus(
                provider=getattr(self.inner, "provider", self.settings.payment_mode),
                status="missing",
                provider_ref="",
                payload={},
            )
        getter = getattr(self.inner, "get_donation_status", None)
        if getter is None:
            status = PaymentStatus(
                provider=getattr(self.inner, "provider", self.settings.payment_mode),
                status="succeeded",
                provider_ref=provider_ref,
                payload={"mode": "test"},
            )
        else:
            status = getter(provider_ref)
        attempts = [
            attempt
            for attempt in self.repo.list_payment_attempts(pact.id)
            if attempt.provider_ref == provider_ref
        ]
        if attempts:
            attempt = attempts[-1]
            self.repo.save_payment_attempt(
                attempt.model_copy(
                    update={
                        "status": status.status,
                        "approval_status": status.status,
                        "updated_at": self.clock.now(),
                    }
                )
            )
        return status


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

    def __init__(
        self,
        link_mode: str = "dry_run",
        *,
        payment_method_id: str | None = None,
        runner: LinkCliRunner | None = None,
        timeout_seconds: int = 600,
    ):
        self.link_mode = link_mode
        self.payment_method_id = payment_method_id
        self.runner = runner or SubprocessLinkCliRunner()
        self.timeout_seconds = timeout_seconds

    def create_donation(self, pact: Pact, idempotency_key: str) -> PaymentResult:
        if self.link_mode == "dry_run":
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
        if self.link_mode != "live":
            raise RuntimeError(f"unsupported Link mode {self.link_mode!r}")
        if not self.payment_method_id:
            raise RuntimeError("Link live mode requires a payment method id")

        charity = get_charity(pact.charity_id)
        merchant_name = charity["name"] if charity else pact.charity_id
        merchant_url = charity["donation_url"] if charity else pact.charity_url
        context = (
            f"Pact failed for {pact.owner or 'the Pact owner'}: {pact.title}. "
            f"Pact id {pact.id} owes a {pact.stake_amount_cents} cent donation "
            f"to {merchant_name}. The user must explicitly approve this Link "
            "spend request before any credential is issued or money can move."
        )
        line_item = (
            "name:Pact donation,"
            f"unit_amount:{pact.stake_amount_cents},"
            "quantity:1,"
            f"description:{pact.title}"
        )
        total = f"type:total,display_text:Donation,amount:{pact.stake_amount_cents}"
        args = [
            "link-cli",
            "spend-request",
            "create",
            "--format",
            "json",
            "--payment-method-id",
            self.payment_method_id,
            "--credential-type",
            "card",
            "--amount",
            str(pact.stake_amount_cents),
            "--currency",
            pact.currency,
            "--merchant-name",
            merchant_name,
            "--merchant-url",
            merchant_url,
            "--context",
            context,
            "--line-item",
            line_item,
            "--total",
            total,
        ]
        payload = self.runner.run(args, timeout=self.timeout_seconds)
        provider_ref = _extract_provider_ref(payload)
        if not provider_ref:
            raise RuntimeError("link-cli spend-request response missing id")
        return PaymentResult(
            provider="link_cli",
            status=_extract_status(payload),
            provider_ref=str(provider_ref),
            payload={
                "charity_id": pact.charity_id,
                "amount_cents": pact.stake_amount_cents,
                "idempotency_key": idempotency_key,
                "mode": "live",
                "link_cli": payload,
            },
        )

    def get_donation_status(self, provider_ref: str) -> PaymentStatus:
        payload = self.runner.run(
            [
                "link-cli",
                "spend-request",
                "retrieve",
                provider_ref,
                "--format",
                "json",
                "--timeout",
                "1",
                "--interval",
                "0",
                "--max-attempts",
                "1",
            ],
            timeout=30,
        )
        ref = _extract_provider_ref(payload) or provider_ref
        return PaymentStatus(
            provider="link_cli",
            status=_extract_status(payload),
            provider_ref=str(ref),
            payload={"mode": self.link_mode, "link_cli": payload},
        )


def get_payment_provider(settings: Settings) -> PaymentProvider:
    """Select the payment provider from Settings.

    Defaults to the recording-safe ``TestLinkProvider``; returns a (still safe,
    dry-run-by-default) ``LinkCliProvider`` only when ``payment_mode == "link_cli"``.
    """
    if settings.payment_mode == "link_cli":
        return LinkCliProvider(
            link_mode=settings.link_mode,
            payment_method_id=settings.link_payment_method_id,
        )
    return TestLinkProvider()

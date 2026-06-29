import subprocess
import json
from dataclasses import dataclass
from hashlib import sha1
from typing import Protocol, runtime_checkable

from pact.config import Settings
from pact.charities import get_charity
from pact.models import Pact, PaymentAttempt


class LinkChargeAmbiguous(Exception):
    """A spend-request subprocess was invoked but its outcome is unknown.

    Raised when ``link-cli`` was actually shelled out to during charge creation but
    the call failed in a way that does not tell us whether the request was created
    (timeout, non-zero exit after the request may have fired, unparseable output).
    The caller must NOT treat this as a clean failure (money may have moved) and
    must NOT blindly retry (``link-cli`` has no idempotency key, so a retry could
    double-charge) — it should park the pact for manual reconciliation instead.
    """


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
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout,
            )
        except subprocess.CalledProcessError as exc:
            # Surface link-cli's own stderr/stdout so the recorded attempt and the
            # API error carry the real cause instead of a generic CalledProcessError.
            detail = (exc.stderr or exc.stdout or "").strip()
            raise RuntimeError(
                f"link-cli exited {exc.returncode}: {detail or '(no output)'}"
            ) from exc
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

    Live mode (``link_mode == "live"``) shells the real ``link-cli``. The flow is
    deliberately NON-BLOCKING and two-phase so no money moves without an explicit
    human approval:
      1. ``link-cli spend-request create --no-request-approval`` opens the request
         WITHOUT capturing — the default ``--request-approval`` would block and poll
         until approved/denied, which would move money inside this call.
      2. ``link-cli spend-request request-approval <id>`` prompts the human in their
         Link app. This is best-effort: if it fails the request still exists (the id
         is returned) so the user can be re-prompted rather than double-charged.
      3. Capture happens later, when ``get_donation_status`` (``retrieve``) reports
         the human has approved — see the API's ``/donation/approve`` path.

    ``link_mode == "live_test"`` is identical but appends ``--test`` to every call,
    so the real subprocess path can be exercised against Link test credentials with
    no real money. It is the only safe way to integration-test the live argv/parsing.
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
        if self.link_mode not in ("live", "live_test"):
            raise RuntimeError(f"unsupported Link mode {self.link_mode!r}")
        if not self.payment_method_id:
            raise RuntimeError("Link live mode requires a payment method id")
        test_mode = self.link_mode == "live_test"

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
            # Open the request WITHOUT polling/capturing — approval is a separate,
            # human step (see request-approval below). Otherwise link-cli would block
            # and move money inside this call.
            "--no-request-approval",
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
        if test_mode:
            args.append("--test")
        try:
            payload = self.runner.run(args, timeout=self.timeout_seconds)
        except Exception as exc:
            # We shelled out, so the request may have been created — never claim a
            # clean failure or blindly retry. Let the caller park for reconcile.
            raise LinkChargeAmbiguous(
                f"link-cli spend-request create outcome unknown: {exc}"
            ) from exc
        provider_ref = _extract_provider_ref(payload)
        if not provider_ref:
            raise LinkChargeAmbiguous("link-cli spend-request response missing id")

        # Best-effort: ask Link to prompt the human for approval. A failure here does
        # NOT lose the created request (the ref is returned and persisted), so the
        # user can be re-prompted rather than charged twice.
        approval_args = [
            "link-cli",
            "spend-request",
            "request-approval",
            str(provider_ref),
            "--format",
            "json",
        ]
        if test_mode:
            approval_args.append("--test")
        approval_payload: dict = {}
        try:
            approval_payload = self.runner.run(approval_args, timeout=30)
        except Exception as exc:  # non-fatal — the request still exists
            approval_payload = {"request_approval_error": str(exc)}

        status = _extract_status(approval_payload)
        if status == "unknown":
            status = _extract_status(payload)
        return PaymentResult(
            provider="link_cli",
            status=status,
            provider_ref=str(provider_ref),
            payload={
                "charity_id": pact.charity_id,
                "amount_cents": pact.stake_amount_cents,
                "idempotency_key": idempotency_key,
                "mode": self.link_mode,
                "link_cli": payload,
                "request_approval": approval_payload,
            },
        )

    def get_donation_status(self, provider_ref: str) -> PaymentStatus:
        args = [
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
        ]
        if self.link_mode == "live_test":
            args.append("--test")
        payload = self.runner.run(args, timeout=30)
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

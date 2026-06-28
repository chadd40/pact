"""Link funding connection — the post-first-pact 'connect a funding source' step.

Pact is charge-on-fail, never escrow: 'connecting' Link does NOT move or hold
money. It registers a funding reference so that, if a pact later fails, the
existing settlement path is allowed to create the donation charge. In this
local-first build the reference is a deterministic TEST value and no real card
or money is ever touched. Live wiring stays gated behind explicit config
(see payment.LinkCliProvider).
"""

from __future__ import annotations

from pact.clock import Clock
from pact.models import LinkAccount
from pact.payment import LinkCliRunner, SubprocessLinkCliRunner


def new_account(owner: str) -> LinkAccount:
    """A fresh, disconnected account for an owner."""
    return LinkAccount(owner=owner)


def connect_account(acct: LinkAccount, clock: Clock) -> LinkAccount:
    """Register a (test) funding source. Idempotent: re-connecting is a no-op."""
    if acct.connected:
        return acct
    return acct.model_copy(
        update={
            "connected": True,
            "funding_ref": f"test_funding_{acct.owner}",
            "connected_at": clock.now(),
        }
    )


def _auth_status(payload: dict) -> str:
    status = payload.get("status") or payload.get("auth_status") or payload.get("state")
    if status:
        return str(status)
    if payload.get("authenticated") is True:
        return "authenticated"
    if payload.get("authenticated") is False:
        return "signed_out"
    return "unknown"


def _is_authenticated(payload: dict) -> bool:
    if payload.get("authenticated") is True:
        return True
    status = _auth_status(payload).strip().lower()
    return status in {"authenticated", "authorized", "logged_in", "logged-in", "ok", "ready"}


def _method_items(payload: dict) -> list[dict]:
    raw = (
        payload.get("payment_methods")
        or payload.get("paymentMethods")
        or payload.get("methods")
        or payload.get("data")
        or payload
    )
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        items = raw.get("items") or raw.get("payment_methods") or raw.get("methods")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _method_id(method: dict) -> str | None:
    raw = method.get("id") or method.get("payment_method_id") or method.get("paymentMethodId")
    return str(raw) if raw else None


def _method_last4(method: dict) -> str | None:
    card = method.get("card")
    raw = method.get("last4")
    if raw is None and isinstance(card, dict):
        raw = card.get("last4")
    return str(raw) if raw else None


def _method_label(method: dict) -> str | None:
    raw = method.get("label") or method.get("brand") or method.get("name")
    if raw is None and isinstance(method.get("card"), dict):
        raw = method["card"].get("brand")
    return str(raw) if raw else None


def _is_usable_method(method: dict) -> bool:
    if not _method_id(method):
        return False
    status = str(method.get("status") or method.get("state") or "active").strip().lower()
    return status not in {"disabled", "expired", "removed", "unavailable", "failed"}


def _select_method(methods: list[dict], preferred_id: str | None) -> dict | None:
    usable = [m for m in methods if _is_usable_method(m)]
    if preferred_id:
        for method in usable:
            if _method_id(method) == preferred_id:
                return method
        return None
    return usable[0] if usable else None


def _not_ready(acct: LinkAccount, clock: Clock, auth_status: str, error: str) -> LinkAccount:
    return acct.model_copy(
        update={
            "connected": False,
            "funding_ref": None,
            "payment_method_id": None,
            "payment_method_label": None,
            "payment_method_last4": None,
            "auth_status": auth_status,
            "checked_at": clock.now(),
            "error": error,
        }
    )


def refresh_live_account(
    acct: LinkAccount,
    clock: Clock,
    *,
    runner: LinkCliRunner | None = None,
    preferred_payment_method_id: str | None = None,
    allow_login: bool = False,
    allow_add_method: bool = False,
    timeout_seconds: int = 120,
) -> LinkAccount:
    """Check Link CLI readiness and store only non-secret funding metadata."""
    runner = runner or SubprocessLinkCliRunner()
    auth = runner.run(["link-cli", "auth", "status", "--format", "json"], timeout_seconds)
    auth_status = _auth_status(auth)

    if not _is_authenticated(auth) and allow_login:
        runner.run(["link-cli", "auth", "login", "--client-name", "Pact"], timeout_seconds)
        auth = runner.run(["link-cli", "auth", "status", "--format", "json"], timeout_seconds)
        auth_status = _auth_status(auth)

    if not _is_authenticated(auth):
        return _not_ready(acct, clock, auth_status, "Link CLI is not authenticated")

    methods_payload = runner.run(
        ["link-cli", "payment-methods", "list", "--format", "json"], timeout_seconds
    )
    methods = _method_items(methods_payload)
    method = _select_method(methods, preferred_payment_method_id)

    if method is None and allow_add_method:
        runner.run(["link-cli", "payment-methods", "add"], timeout_seconds)
        methods_payload = runner.run(
            ["link-cli", "payment-methods", "list", "--format", "json"], timeout_seconds
        )
        method = _select_method(_method_items(methods_payload), preferred_payment_method_id)

    if method is None:
        if preferred_payment_method_id:
            error = f"Link payment method {preferred_payment_method_id!r} is not available"
        else:
            error = "No usable Link payment method is available"
        return _not_ready(acct, clock, auth_status, error)

    payment_method_id = _method_id(method)
    connected_at = acct.connected_at or clock.now()
    return acct.model_copy(
        update={
            "connected": True,
            "funding_ref": payment_method_id,
            "connected_at": connected_at,
            "payment_method_id": payment_method_id,
            "payment_method_label": _method_label(method),
            "payment_method_last4": _method_last4(method),
            "auth_status": auth_status,
            "checked_at": clock.now(),
            "error": None,
        }
    )


def is_owner_connected(repo, owner: str | None) -> bool:
    """True iff this owner has a connected funding source. Settlement callers use
    this to decide whether the charge-on-fail donation may fire."""
    if not owner:
        return False
    acct = repo.get_link_account(owner)
    return bool(acct and acct.connected)

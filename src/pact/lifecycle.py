from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from pact.models import Pact, PactStatus, StakeState


class TransitionError(Exception):
    """Raised when a requested lifecycle transition is not allowed."""


class PactRefused(Exception):
    """Raised when a draft is refused by the reasoning provider."""


ALLOWED_TRANSITIONS: dict[PactStatus, set[PactStatus]] = {
    PactStatus.draft: {
        PactStatus.active,
        PactStatus.canceled_release,
        PactStatus.canceled_forfeit,
    },
    PactStatus.active: {
        PactStatus.evaluating,
        PactStatus.canceled_release,
        PactStatus.canceled_forfeit,
    },
    PactStatus.evaluating: {
        PactStatus.succeeded,
        PactStatus.failed,
        PactStatus.needs_review,
    },
    PactStatus.needs_review: {
        PactStatus.succeeded,
        PactStatus.failed,
        PactStatus.evaluating,
    },
    PactStatus.failed: {
        PactStatus.donation_pending,
    },
    PactStatus.canceled_forfeit: {
        PactStatus.donation_pending,
    },
    PactStatus.donation_pending: {
        PactStatus.donated,
        PactStatus.donation_failed,
        PactStatus.donation_declined,
    },
    PactStatus.succeeded: set(),
    PactStatus.canceled_release: set(),
    PactStatus.donated: set(),
    PactStatus.donation_failed: set(),
    PactStatus.donation_declined: set(),
}


def transition(pact: Pact, new: PactStatus) -> Pact:
    allowed = ALLOWED_TRANSITIONS.get(pact.status, set())
    if new not in allowed:
        raise TransitionError(
            f"Cannot transition from {pact.status} to {new}; "
            f"allowed: {sorted(s.value for s in allowed)}"
        )
    pact.status = new
    return pact


def new_pact_id(seed: str) -> str:
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return "pact_" + digest[:6]


# ─── Task 13 additions ────────────────────────────────────────────────────────

from pact.clock import Clock
from pact.config import Settings
from pact.models import (
    Modality,
    Proof,
    ProofStatus,
    Rubric,
    StakeState,
    TaskType,
)
from pact.anticheat import TokenStore, day_bucket, find_duplicate, phash_hex
from pact.charities import get_charity, is_allowed_url
from pact.reasoning import ReasoningProvider, make_reasoning_task


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def draft_pact(
    prompt: str,
    provider: ReasoningProvider,
    clock: Clock,
    settings: Settings,
) -> Pact:
    task = make_reasoning_task(TaskType.draft, None, {"prompt": prompt}, clock)
    result = provider.resolve(task)
    if result.get("refused"):
        raise PactRefused(result.get("reason", "Pact refused."))

    recommended = _clamp(
        int(result["recommended_stake_cents"]),
        settings.min_stake_cents,
        settings.max_stake_cents,
    )
    rubric = Rubric.model_validate(result["rubric"])
    now = clock.now()
    return Pact(
        id=new_pact_id(prompt + result["deadline_iso"]),
        owner="",
        original_prompt=prompt,
        title=result["title"],
        goal=result["goal"],
        timezone=result["timezone"],
        deadline_at=datetime.fromisoformat(result["deadline_iso"]),
        target_count=int(result["target_count"]),
        recommended_stake_cents=recommended,
        stake_amount_cents=recommended,
        charity_id="",
        charity_url="",
        freezes_allowed=settings.default_freezes,
        freeze_extension_hours=settings.freeze_extension_hours,
        rubric=rubric,
        status=PactStatus.draft,
        stake_state=StakeState.none,
        created_at=now,
    )


def confirm_and_start(
    pact: Pact,
    stake_amount_cents: int,
    charity_id: str,
    clock: Clock,
    settings: Settings,
) -> Pact:
    if not (settings.min_stake_cents <= stake_amount_cents <= settings.max_stake_cents):
        raise ValueError(
            f"stake {stake_amount_cents} outside caps "
            f"[{settings.min_stake_cents}, {settings.max_stake_cents}]"
        )
    charity = get_charity(charity_id)
    if charity is None:
        raise ValueError(f"unknown charity {charity_id!r}")
    charity_url = charity["donation_url"]
    if not is_allowed_url(charity_id, charity_url):
        raise ValueError(f"charity url {charity_url!r} not on allowlist for {charity_id!r}")

    started = pact.model_copy(
        update={
            "stake_amount_cents": stake_amount_cents,
            "charity_id": charity_id,
            "charity_url": charity_url,
            "status": PactStatus.active,
            "stake_state": StakeState.committed,
            "started_at": clock.now(),
        }
    )
    return started


def submit_proof(
    pact: Pact,
    modality: Modality,
    token: str,
    token_in_image: bool,
    content_ok: bool,
    image_path: str | None,
    tokens: TokenStore,
    provider: ReasoningProvider,
    clock: Clock,
    prior_phashes: list[str] | None = None,
) -> Proof:
    now = clock.now()
    token_ok = tokens.verify(pact.id, token, clock)
    bucket = day_bucket(now, pact.timezone)

    phash: str | None = None
    dup_of: str | None = None
    if image_path is not None:
        phash = phash_hex(image_path)
        existing = prior_phashes or []
        idx = find_duplicate(phash, existing)
        if idx is not None:
            dup_of = existing[idx]

    task = make_reasoning_task(
        TaskType.judge_proof,
        pact.id,
        {
            "token_ok": token_ok,
            "is_duplicate": dup_of is not None,
            "content_ok": content_ok,
            "rubric": pact.rubric.model_dump(),
        },
        clock,
    )
    result = provider.resolve(task)

    return Proof(
        id=new_pact_id(pact.id + token + now.isoformat()).replace("pact_", "proof_"),
        pact_id=pact.id,
        modality=modality,
        received_at=now,
        day_bucket=bucket,
        token_issued=token,
        token_ok=token_ok,
        phash=phash,
        dup_of=dup_of,
        artifact_path=image_path,
        status=ProofStatus(result["status"]),
        judge_reason=result["reason"],
        judge_checklist=result["checklist"],
    )


# ─── Task 14: freeze + cancel ─────────────────────────────────────────────────


def spend_freeze(pact: Pact, clock: Clock) -> Pact:
    if pact.freezes_used >= pact.freezes_allowed:
        raise TransitionError(
            f"no freezes left: used {pact.freezes_used} of {pact.freezes_allowed}"
        )
    pact.deadline_at = pact.deadline_at + timedelta(hours=pact.freeze_extension_hours)
    pact.freezes_used += 1
    return pact


def cancel(pact: Pact, clock: Clock, settings: Settings) -> Pact:
    now = clock.now()
    cooling_off_end = pact.started_at + timedelta(minutes=settings.cooling_off_minutes)
    if now <= cooling_off_end:
        pact = transition(pact, PactStatus.canceled_release)
        pact.stake_state = StakeState.released
        return pact
    pact = transition(pact, PactStatus.canceled_forfeit)
    pact = transition(pact, PactStatus.donation_pending)
    return pact


# ─── Task 15: settle + submit_dispute ─────────────────────────────────────────

from pact.anticheat import count_distinct_valid_days
from pact.models import (
    PaymentAction,
    Proof,
    Verdict,
)
from pact.payment import PaymentProvider

_TERMINAL_STATUSES = {
    PactStatus.succeeded,
    PactStatus.donated,
    PactStatus.donation_failed,
    PactStatus.donation_declined,
    PactStatus.canceled_release,
    PactStatus.canceled_forfeit,
}


def _valid_count(pact: Pact, proofs: list[Proof]) -> int:
    if pact.distinct_days:
        return count_distinct_valid_days(proofs)
    return sum(1 for p in proofs if p.status == ProofStatus.passed)


def _build_verdict(
    pact: Pact,
    proofs: list[Proof],
    valid: int,
    verdict_status: PactStatus,
    payment_action: PaymentAction,
    payment_ref: str | None,
) -> Verdict:
    if verdict_status == PactStatus.succeeded:
        summary = (
            f"{valid} of {pact.target_count} valid proofs by deadline. Pact succeeded."
        )
    else:
        summary = (
            f"{valid} of {pact.target_count} valid proofs by deadline. Pact failed."
        )
    return Verdict(
        pact_id=pact.id,
        status=verdict_status,
        valid_proof_count=valid,
        target_count=pact.target_count,
        freezes_used=pact.freezes_used,
        summary=summary,
        proof_ids=[p.id for p in proofs],
        payment_action=payment_action,
        payment_ref=payment_ref,
        honesty_note=(
            "Commitment device; proofs judged best-effort, not forensically verified."
        ),
    )


def settle(
    pact: Pact,
    proofs: list[Proof],
    clock: Clock,
    payment: PaymentProvider,
) -> tuple[Pact, Verdict]:
    now = clock.now()

    # Idempotent: a pact already in a terminal donation/success state is returned
    # unchanged together with a rebuilt verdict reflecting the prior payment.
    if pact.status in _TERMINAL_STATUSES:
        valid = _valid_count(pact, proofs)
        if pact.spend_request_id is not None:
            action = PaymentAction.donation_executed
            ref = pact.spend_request_id
            verdict_status = PactStatus.failed
        elif pact.status == PactStatus.succeeded:
            action = PaymentAction.none
            ref = None
            verdict_status = PactStatus.succeeded
        else:
            action = PaymentAction.none
            ref = pact.spend_request_id
            verdict_status = PactStatus.failed
        return pact, _build_verdict(pact, proofs, valid, verdict_status, action, ref)

    valid = _valid_count(pact, proofs)

    if valid >= pact.target_count:
        pact.status = PactStatus.succeeded
        pact.stake_state = StakeState.released
        pact.verdict_at = now
        # SUCCESS: no payment call, no spend_request_id.
        return pact, _build_verdict(pact, proofs, valid, PactStatus.succeeded, PaymentAction.none, None)

    # FAIL path. Charge-on-fail, exactly once, guarded by spend_request_id.
    pact.status = PactStatus.failed
    if pact.spend_request_id is None:
        pact.status = PactStatus.donation_pending
        result = payment.create_donation(pact, f"{pact.id}:donation")
        pact.spend_request_id = result.provider_ref
        pact.stake_state = StakeState.executed
        pact.status = PactStatus.donated
    pact.verdict_at = now
    return pact, _build_verdict(
        pact, proofs, valid, PactStatus.failed, PaymentAction.donation_executed, pact.spend_request_id
    )


def submit_dispute(
    pact: Pact,
    proofs: list[Proof],
    clock: Clock,
    payment: PaymentProvider,
) -> tuple[Pact, Verdict]:
    # A dispute is allowed exactly once: only a failed/donated pact may be disputed,
    # and a successful re-run (or an already-disputed pact) closes the window for good.
    if pact.status not in {
        PactStatus.failed,
        PactStatus.donation_pending,
        PactStatus.donated,
        PactStatus.donation_failed,
        PactStatus.donation_declined,
    }:
        raise TransitionError(
            f"dispute not allowed from status {pact.status}"
        )

    valid = _valid_count(pact, proofs)
    if valid >= pact.target_count:
        # Extra proof clears the bar -> overturn to success, final.
        pact.status = PactStatus.succeeded
        pact.stake_state = StakeState.released
        pact.verdict_at = clock.now()
        return pact, _build_verdict(pact, proofs, valid, PactStatus.succeeded, PaymentAction.none, None)

    # Still short: donation already executed once; re-affirm the failed verdict, final.
    pact.verdict_at = clock.now()
    action = (
        PaymentAction.donation_executed
        if pact.spend_request_id is not None
        else PaymentAction.none
    )
    return pact, _build_verdict(pact, proofs, valid, PactStatus.failed, action, pact.spend_request_id)

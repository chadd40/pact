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
    consent_acknowledged: bool = False,
) -> Pact:
    # Honest acknowledgment, not a compliance gate: a pact cannot start until the
    # owner explicitly acknowledges that real money goes to charity on failure.
    if not consent_acknowledged:
        raise ValueError(
            "consent_acknowledged must be True to start a pact "
            "(money goes to charity on failure)"
        )
    if not (settings.min_stake_cents <= stake_amount_cents <= settings.max_stake_cents):
        raise ValueError(
            f"stake {stake_amount_cents} outside caps "
            f"[{settings.min_stake_cents}, {settings.max_stake_cents}]"
        )
    charity = get_charity(charity_id)
    if charity is None:
        raise ValueError(f"unknown charity {charity_id!r}")
    charity_url = charity["donation_url"]
    # Defensive: the catalog's donation_url should always sit on the charity's own
    # allowed_domains, so this never fires for the shipped catalog. It guards against
    # catalog corruption -- e.g. a future edit that changes donation_url without
    # updating allowed_domains -- catching the incoherence before we stake on it.
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
    try:
        result = provider.resolve(task)
        proof_status = ProofStatus(result["status"])
        judge_reason = result["reason"]
        judge_checklist = result["checklist"]
    except Exception:
        # Money-safety: if the resolver is unavailable/errors, do NOT crash the
        # request and do NOT silently pass/fail. Park the proof as ambiguous so a
        # later re-judge can resolve it; settle() treats decisive ambiguity as
        # needs_review and never donates off an unjudged proof.
        proof_status = ProofStatus.ambiguous
        judge_reason = "judging unavailable (resolver error)"
        judge_checklist = {}

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
        status=proof_status,
        judge_reason=judge_reason,
        judge_checklist=judge_checklist,
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
    settings: Settings,
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
        # SUCCESS: no payment call, no spend_request_id, no dispute window.
        return pact, _build_verdict(
            pact, proofs, valid, PactStatus.succeeded, PaymentAction.none, None
        )

    # needs_review: the verdict is FAIL, but unjudged (ambiguous) proofs on days
    # not already counted could lift `valid` to target if they re-judge to passed.
    # valid_passed < target <= valid_passed + ambiguous_distinct_days. Park the
    # pact: NO donation, NO dispute window, stake stays committed. A later settle
    # (after the ambiguous proofs are re-judged) flows through normally because
    # needs_review is not terminal and not handled here.
    passed_days = {p.day_bucket for p in proofs if p.status == ProofStatus.passed}
    ambiguous_distinct_days = len(
        {
            p.day_bucket
            for p in proofs
            if p.status == ProofStatus.ambiguous and p.day_bucket not in passed_days
        }
    )
    if valid < pact.target_count <= valid + ambiguous_distinct_days:
        pact.status = PactStatus.needs_review
        pact.verdict_at = now
        # No payment, no spend_request_id, no dispute_window_closes_at.
        return pact, _build_verdict(
            pact, proofs, valid, PactStatus.needs_review, PaymentAction.none, None
        )

    # FAIL path: DEFER the donation. Open a pre-donation dispute window; the stake
    # stays committed and no money moves until close_dispute_window fires after the
    # window closes. Idempotent re-settle on an already-failed pact only refreshes
    # the window-close horizon if it was never set.
    pact.status = PactStatus.failed
    if pact.dispute_window_closes_at is None:
        pact.dispute_window_closes_at = now + timedelta(hours=settings.dispute_grace_hours)
    pact.verdict_at = now
    return pact, _build_verdict(
        pact, proofs, valid, PactStatus.failed, PaymentAction.none, None
    )


def close_dispute_window(
    pact: Pact,
    proofs: list[Proof],
    clock: Clock,
    payment: PaymentProvider,
    settings: Settings,
    link_connected: bool = True,
) -> tuple[Pact, Verdict]:
    """Execute the deferred donation once the dispute window has closed.

    Money moves here, not in settle. Guarded by spend_request_id so a second
    close (e.g. a restart re-sweep) moves no additional money. A pact that was
    overturned to success inside the window never reaches the donation branch.

    `link_connected` gates the charge: Pact is charge-on-fail, but a charge can
    only fire if the owner has connected a funding source (see link.py). When it
    is not connected, the donation is deferred — the pact parks at
    `donation_pending` (no money path) and a later close (after the user
    connects Link) fires it. Defaults True so every existing caller is unchanged.
    """
    now = clock.now()
    valid = _valid_count(pact, proofs)

    # Already donated: idempotent rebuild, no second donation.
    if pact.spend_request_id is not None:
        return pact, _build_verdict(
            pact, proofs, valid, PactStatus.failed,
            PaymentAction.donation_executed, pact.spend_request_id,
        )

    # A still-failing pact past its closed window with no prior donation and a
    # genuine shortfall owes the deferred donation. `donation_pending` is included
    # so a pact deferred for a missing funding source re-fires on a later close.
    window = pact.dispute_window_closes_at
    if (
        pact.status in (PactStatus.failed, PactStatus.donation_pending)
        and window is not None
        and now >= window
        and valid < pact.target_count
    ):
        if not link_connected:
            # No funding source connected: park at donation_pending, move no money.
            # The web/agent prompt the owner to connect Link; the next close fires.
            pact.status = PactStatus.donation_pending
            return pact, _build_verdict(
                pact, proofs, valid, PactStatus.failed, PaymentAction.none, None
            )
        pact.status = PactStatus.donation_pending
        try:
            result = payment.create_donation(pact, f"{pact.id}:donation")
        except Exception:
            # Provider raised mid-charge: do NOT leave the pact re-enterable. A
            # None spend_request_id would re-trigger create_donation on the next
            # sweep and risk a double-donation. Park it at terminal donation_failed
            # (no money moved here) so a human can investigate/retry deliberately.
            pact.status = PactStatus.donation_failed
            pact.stake_state = StakeState.error
            pact.verdict_at = now
            return pact, _build_verdict(
                pact, proofs, valid, PactStatus.failed,
                PaymentAction.donation_failed, None,
            )
        pact.spend_request_id = result.provider_ref
        pact.stake_state = StakeState.executed
        pact.status = PactStatus.donated
        pact.verdict_at = now
        return pact, _build_verdict(
            pact, proofs, valid, PactStatus.failed,
            PaymentAction.donation_executed, pact.spend_request_id,
        )

    # Window still open (or pact no longer failing / already terminal): no-op.
    verdict_status = (
        PactStatus.succeeded if pact.status == PactStatus.succeeded else PactStatus.failed
    )
    return pact, _build_verdict(pact, proofs, valid, verdict_status, PaymentAction.none, None)


def decline_donation(pact: Pact, clock: Clock) -> Pact:
    """The owner explicitly declines a pending donation while looking at the
    failure evidence (the 'nag until resolved' exit). Only valid from
    `donation_pending`; idempotent if already declined. The miss itself was
    already recorded at finalization — this only resolves the open donation so
    the agent stops nagging. No money moves.
    """
    if pact.status == PactStatus.donation_declined:
        return pact
    if pact.status != PactStatus.donation_pending:
        raise TransitionError(f"cannot decline a donation from status {pact.status.value}")
    pact.status = PactStatus.donation_declined
    pact.stake_state = StakeState.declined
    pact.verdict_at = clock.now()
    return pact


def execute_forfeit_donation(
    pact: Pact,
    clock: Clock,
    payment: PaymentProvider,
) -> Pact:
    """Move the stake for a forfeited cancel (status donation_pending).

    `cancel` parks a post-cooling-off forfeit in `donation_pending` without
    moving any money (mirrors the deferred dispute-window posture). This helper
    executes that pending donation exactly once: it creates the donation, records
    the spend-request id, marks the stake executed, and transitions to `donated`.

    Idempotent on `spend_request_id`: once the donation has fired, a second call
    is a no-op and moves no further money. Anything not in `donation_pending`
    (e.g. a release, or an already-`donated` pact) is returned unchanged.
    """
    if pact.status != PactStatus.donation_pending:
        return pact
    if pact.spend_request_id is not None:
        return pact

    try:
        result = payment.create_donation(pact, f"{pact.id}:donation")
    except Exception:
        # Provider raised: mark terminal donation_failed rather than leaving the
        # pact re-enterable (which would risk a second charge on retry). No money
        # moved (spend_request_id stays None).
        pact = transition(pact, PactStatus.donation_failed)
        pact.stake_state = StakeState.error
        pact.verdict_at = clock.now()
        return pact
    pact.spend_request_id = result.provider_ref
    pact.stake_state = StakeState.executed
    pact = transition(pact, PactStatus.donated)
    pact.verdict_at = clock.now()
    return pact


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
        # Extra proof clears the bar within the open window -> overturn to success,
        # final. No donation; close the window so a later sweep never donates.
        pact.status = PactStatus.succeeded
        pact.stake_state = StakeState.released
        pact.dispute_window_closes_at = None
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


# ─── Task 16: startup reconciliation ──────────────────────────────────────────

from pact.repository import Repository


def create_pact_structured(
    *,
    goal_title: str,
    goal_template: str | None,
    days_per_week: int,
    weeks: int,
    stake_amount_cents: int,
    charity_id: str,
    agent: str | None,
    consent_acknowledged: bool,
    owner: str,
    clock: Clock,
    settings: Settings,
    original_prompt: str = "",
) -> Pact:
    """Build an ACTIVE pact directly from structured UI inputs.

    Validates consent, stake cap, and charity before constructing the pact so
    the caller can persist it unconditionally on success.
    """
    if not consent_acknowledged:
        raise ValueError(
            "consent_acknowledged must be True to start a pact "
            "(money goes to charity on failure)"
        )
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

    now = clock.now()
    target_count = days_per_week * weeks
    deadline_at = now + timedelta(weeks=weeks)

    # A sensible default photo rubric mirroring the TestLLMProvider._draft shape.
    min_distinct_days = min(max(target_count, 1), max(target_count - 1, 4))
    # Ensure min_distinct_days never exceeds count_target.
    min_distinct_days = min(min_distinct_days, target_count)
    rubric = Rubric(
        modality=Modality.photo,
        require_token=True,
        must_show=["clear evidence the committed action was performed"],
        reject_if=["stock/watermark", "pure UI screenshot", "missing token"],
        min_distinct_days=min_distinct_days,
        count_target=target_count,
        rest_if_injured_counts=True,
        rigor_floor={
            "require_token": True,
            "min_distinct_days": min_distinct_days,
            "non_negotiable": [
                "require_token",
                "server_time_is_truth",
                "no_duplicates",
            ],
        },
    )

    template_note = f" (template: {goal_template})" if goal_template else ""
    goal = (
        f"Complete the committed action {target_count} times on {target_count} "
        f"distinct days over {weeks} week{'s' if weeks != 1 else ''}{template_note}."
    )

    pact_id = new_pact_id(goal_title + now.isoformat() + owner)

    return Pact(
        id=pact_id,
        owner=owner,
        original_prompt=original_prompt or goal_title,
        title=goal_title,
        goal=goal,
        timezone="America/Los_Angeles",
        deadline_at=deadline_at,
        target_count=target_count,
        distinct_days=True,
        days_per_week=days_per_week,
        weeks=weeks,
        recommended_stake_cents=stake_amount_cents,
        stake_amount_cents=stake_amount_cents,
        charity_id=charity_id,
        charity_url=charity_url,
        agent=agent,
        freezes_allowed=settings.default_freezes,
        freeze_extension_hours=settings.freeze_extension_hours,
        rubric=rubric,
        status=PactStatus.active,
        stake_state=StakeState.committed,
        created_at=now,
        started_at=now,
    )


def reconcile_on_startup(
    repo: Repository,
    clock: Clock,
    payment: PaymentProvider,
    settings: Settings,
) -> list[Pact]:
    """Settle every due active pact, then execute any deferred donations whose
    dispute window has now closed.

    Spec §5: a startup/ticker sweep drives the ghosting failure path —
    no proofs by deadline -> failed (window opens) -> after the window closes,
    donation, with zero user interaction. Relies on `settle` and
    `close_dispute_window` being idempotent, so a restart mid-pact (a second
    sweep) re-settles nothing and moves no additional money.
    """
    now = clock.now()
    touched: list[Pact] = []

    # Stage 1: deadline sweep — settle due active pacts (success releases; fail opens window).
    for pact in repo.due_active_pacts(now):
        proofs = repo.list_proofs(pact.id)
        updated, verdict = settle(pact, proofs, clock, payment, settings)
        repo.update_pact(updated)
        repo.save_verdict(verdict)
        touched.append(updated)

    # Stage 2: grace sweep — close any failed pact whose dispute window has elapsed.
    for pact in repo.list_pacts():
        if (
            pact.status == PactStatus.failed
            and pact.spend_request_id is None
            and pact.dispute_window_closes_at is not None
            and now >= pact.dispute_window_closes_at
        ):
            proofs = repo.list_proofs(pact.id)
            closed, verdict = close_dispute_window(pact, proofs, clock, payment, settings)
            repo.update_pact(closed)
            repo.save_verdict(verdict)
            touched.append(closed)

    return touched

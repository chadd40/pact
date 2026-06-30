from __future__ import annotations

from pact.charities import get_charity
from pact.clock import Clock
from pact.coaching import (
    donation_nag_message,
    failed_dispute_message,
    generate_coach_message,
    renew_message,
    should_nudge,
)
from pact.config import Settings
from pact.lifecycle import close_dispute_window, settle
from pact.link import is_owner_connected
from pact.models import PactStatus, Profile
from pact.payment import PaymentProvider
from pact.profile import record_outcome
from pact.repository import Repository


def _charity_name(charity_id: str) -> str:
    charity = get_charity(charity_id)
    return charity["name"] if charity is not None else charity_id


def _get_fallback_provider():
    """Return a cached TestLLMProvider for coach prose generation in the ticker.

    Lazy-loaded so the import doesn't run at module-import time.
    """
    from pact.reasoning import TestLLMProvider
    return TestLLMProvider()


def tick(
    repo: Repository,
    clock: Clock,
    payment: PaymentProvider,
    settings: Settings,
) -> dict:
    """One scheduler sweep. Three idempotent passes, in order.

    1. Reconcile: settle every due active pact. With the Day-3 settle, a FAIL
       opens the dispute window (status -> failed) and moves NO money.
    2. Close windows: for every failed pact whose dispute window has elapsed,
       close_dispute_window executes the deferred donation exactly once and we
       fold the failure into the owner Profile (record_outcome is idempotent).
    3. Nudge: for every still-active pact where should_nudge fires, generate +
       persist a CoachingMessage (delivered_at=None) into the outbox. The Hermes
       agent relays the nudge through its own channel and marks it delivered via
       POST /api/coach/{id}/delivered. The nag-governor (one outbound per calendar
       day, suppress if a proof landed today) makes this at-most-once per pact per
       day, so a second tick the same day is a no-op.

    Returns a summary dict: {"now", "settled", "donated", "nudged"}.
    Idempotent: re-running at the same instant settles nothing new, donates
    nothing new, and adds no new nudge.
    """
    now = clock.now()
    settled_ids: list[str] = []
    donated_ids: list[str] = []
    nudged_ids: list[str] = []
    nagged_ids: list[str] = []
    failed_ids: list[str] = []
    renewed_ids: list[str] = []

    # ── Pass 1: reconcile due active pacts (settle opens windows). ──────────────
    for pact in repo.due_active_pacts(now):
        proofs = repo.list_proofs(pact.id)
        updated, verdict = settle(pact, proofs, clock, payment, settings)
        repo.update_pact(updated)
        repo.save_verdict(verdict)
        settled_ids.append(updated.id)

    # ── Pass 2: close due dispute windows (deferred donation + profile fail). ───
    # Scan all failed pacts; close_dispute_window is a no-op (returns the failed
    # verdict, no money) until the window has actually closed, and is idempotent
    # once the donation has executed.
    for pact in repo.list_pacts():
        # `donation_pending` is included so a pact deferred for a missing funding
        # source fires its donation on a later tick, once the owner connects Link.
        if pact.status not in (PactStatus.failed, PactStatus.donation_pending):
            continue
        proofs = repo.list_proofs(pact.id)
        # Snapshot before calling — close_dispute_window mutates pact in place,
        # so checking pact.status after the call would always be equal.
        was_failed = pact.status in (PactStatus.failed, PactStatus.donation_pending)
        updated, verdict = close_dispute_window(
            pact, proofs, clock, payment, settings,
            link_connected=(
                False
                if settings.payment_mode == "link_cli" and settings.link_mode == "live"
                else is_owner_connected(repo, pact.owner)
            ),
        )
        if was_failed and updated.status in (PactStatus.donated, PactStatus.donation_pending):
            # The window closed: persist + record the failure (idempotent) at
            # finalization, regardless of whether the human-approved donation has
            # executed yet. Only report it as donated if money actually moved.
            repo.update_pact(updated)
            repo.save_verdict(verdict)
            profile = repo.get_profile(updated.owner) or Profile(owner=updated.owner)
            profile = record_outcome(profile, updated, clock)
            repo.save_profile(profile)
            if updated.status == PactStatus.donated:
                donated_ids.append(updated.id)

    # ── Pass 3: emit at-most-one coach nudge per active pact. ───────────────────
    provider = _get_fallback_provider()
    for pact in repo.list_pacts():
        if pact.status != PactStatus.active:
            continue
        proofs = repo.list_proofs(pact.id)
        messages = repo.list_coaching_messages(pact.id)
        trigger = should_nudge(pact, proofs, messages, clock, nudge_hour=settings.nudge_hour)
        if trigger is None:
            continue
        charity_name = _charity_name(pact.charity_id)
        msg = generate_coach_message(
            pact, proofs, trigger, provider, clock, charity_name
        )
        repo.save_coaching_message(msg)
        nudged_ids.append(pact.id)

    # ── Pass 4: nag unresolved donations until approved or declined. ────────────
    # While a missed pact sits at donation_pending, keep one standing reminder in
    # the outbox. Don't pile up: skip if an undelivered donation_pending nudge is
    # already queued — once the agent relays + marks it delivered, the next tick
    # re-arms it. Resolves when the owner approves (donated) or declines.
    for pact in repo.list_pacts():
        if pact.status != PactStatus.donation_pending:
            continue
        existing = repo.list_coaching_messages(pact.id)
        if any(m.trigger == "donation_pending" and m.delivered_at is None for m in existing):
            continue
        msg = donation_nag_message(pact, clock, _charity_name(pact.charity_id))
        repo.save_coaching_message(msg)
        nagged_ids.append(pact.id)

    # ── Pass 5: at the moment of failure, tell the user they can dispute. ────────
    # One-shot per pact: without this the 24h window passes silently and the dispute
    # feature is unreachable.
    for pact in repo.list_pacts():
        if pact.status != PactStatus.failed or pact.dispute_window_closes_at is None:
            continue
        if any(m.trigger == "failed" for m in repo.list_coaching_messages(pact.id)):
            continue
        repo.save_coaching_message(failed_dispute_message(pact, clock))
        failed_ids.append(pact.id)

    # ── Pass 6: celebrate + prompt a renew on terminal outcomes. ────────────────
    # One-shot per pact when it reaches succeeded or (after a miss) donation_complete.
    for pact in repo.list_pacts():
        if pact.status not in (PactStatus.succeeded, PactStatus.donation_complete):
            continue
        if any(m.trigger == "renew" for m in repo.list_coaching_messages(pact.id)):
            continue
        repo.save_coaching_message(renew_message(pact, clock))
        renewed_ids.append(pact.id)

    return {
        "now": now.isoformat(),
        "settled": settled_ids,
        "donated": donated_ids,
        "nudged": nudged_ids,
        "nagged": nagged_ids,
        "failed": failed_ids,
        "renewed": renewed_ids,
    }


# ─── Tier-1: autonomous ticker loop helper ─────────────────────────────────────

import asyncio
from typing import Awaitable, Callable


async def run_ticker_loop(
    repo: Repository,
    clock: Clock,
    payment: PaymentProvider,
    settings: Settings,
    *,
    stop: asyncio.Event,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    """Drive scheduler.tick on an interval until ``stop`` is set.

    One iteration = one ``tick`` followed by an awaitable ``sleep`` of
    ``settings.scheduler_interval_seconds``. The loop is guarded by ``stop`` so it
    exits cleanly on shutdown, and ``sleep`` is injected so tests pass a no-op (or
    a coroutine that sets ``stop``) and drive a single deterministic iteration with
    no real delay. ``tick`` itself is idempotent, so an extra iteration is harmless.

    Returns the number of ticks executed before ``stop`` fired (useful for tests).
    """
    ticks = 0
    while not stop.is_set():
        tick(repo, clock, payment, settings)
        ticks += 1
        if stop.is_set():
            break
        await sleep(settings.scheduler_interval_seconds)
    return ticks

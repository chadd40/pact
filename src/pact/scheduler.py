from __future__ import annotations

from pact.charities import get_charity
from pact.clock import Clock
from pact.coaching import generate_coach_message, should_nudge
from pact.config import Settings
from pact.lifecycle import close_dispute_window, settle
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
        if pact.status != PactStatus.failed:
            continue
        proofs = repo.list_proofs(pact.id)
        # Snapshot before calling — close_dispute_window mutates pact in place,
        # so checking pact.status after the call would always be equal.
        was_failed = pact.status == PactStatus.failed
        updated, verdict = close_dispute_window(pact, proofs, clock, payment, settings)
        if was_failed and updated.status == PactStatus.donated:
            # The window just closed on this tick: persist, record the failure,
            # and report it as donated.
            repo.update_pact(updated)
            repo.save_verdict(verdict)
            profile = repo.get_profile(updated.owner) or Profile(owner=updated.owner)
            profile = record_outcome(profile, updated, clock)
            repo.save_profile(profile)
            donated_ids.append(updated.id)

    # ── Pass 3: emit at-most-one coach nudge per active pact. ───────────────────
    provider = _get_fallback_provider()
    for pact in repo.list_pacts():
        if pact.status != PactStatus.active:
            continue
        proofs = repo.list_proofs(pact.id)
        messages = repo.list_coaching_messages(pact.id)
        trigger = should_nudge(pact, proofs, messages, clock)
        if trigger is None:
            continue
        charity_name = _charity_name(pact.charity_id)
        msg = generate_coach_message(
            pact, proofs, trigger, provider, clock, charity_name
        )
        repo.save_coaching_message(msg)
        nudged_ids.append(pact.id)

    return {
        "now": now.isoformat(),
        "settled": settled_ids,
        "donated": donated_ids,
        "nudged": nudged_ids,
    }

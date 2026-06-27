from __future__ import annotations

from pact.clock import Clock
from pact.models import Pact, PactStatus, Profile

# Terminal statuses that count as a FAILURE outcome for streak/history purposes.
# Mirrors the failure-side terminal states produced by lifecycle.settle / cancel
# (see ALLOWED_TRANSITIONS and _TERMINAL_STATUSES in src/pact/lifecycle.py).
_FAILURE_STATUSES = {
    PactStatus.failed,
    # A FINALIZED miss whose donation is still being resolved (nag-until-resolved):
    # the streak loss lands now, regardless of whether the human ever approves the
    # charge. Idempotent with the later donated/declined record.
    PactStatus.donation_pending,
    PactStatus.donated,
    PactStatus.donation_failed,
    PactStatus.donation_declined,
    PactStatus.canceled_forfeit,
}


def record_outcome(profile: Profile, pact: Pact, clock: Clock) -> Profile:
    """Fold a pact's terminal outcome into the owner's Profile.

    SUCCESS (status == succeeded): extend the current streak, refresh the best
    streak, and bump `kept`. FAILURE (status in `_FAILURE_STATUSES`): reset the
    current streak to 0 and bump `failed`. Always records the pact id (no dup)
    and appends one history entry.

    Idempotent: a pact already recorded for this same terminal outcome is a
    no-op, so calling twice never double-counts.
    """
    if pact.status == PactStatus.succeeded:
        outcome = "succeeded"
    elif pact.status in _FAILURE_STATUSES:
        outcome = "failed"
    else:
        # Not a terminal outcome we record — return the profile unchanged.
        return profile

    # Idempotency guard: a pact is recorded at most once. Key on pact_id ALONE
    # so a pact can't be double-counted. Callers MUST only invoke record_outcome
    # on a genuinely FINAL outcome -- never on a `failed` pact whose Day-3 dispute
    # window is still open (it has moved no money and may yet be overturned to
    # `succeeded`). The donation/forfeit/success states are reached only after
    # the window closes; see api._TERMINAL_STATUSES and scheduler.tick.
    for entry in profile.history:
        if entry.get("pact_id") == pact.id:
            return profile

    if outcome == "succeeded":
        profile.current_streak += 1
        profile.best_streak = max(profile.best_streak, profile.current_streak)
        profile.kept += 1
    else:
        profile.current_streak = 0
        profile.failed += 1

    if pact.id not in profile.pact_ids:
        profile.pact_ids.append(pact.id)

    profile.history.append(
        {
            "pact_id": pact.id,
            "title": pact.title,
            "outcome": outcome,
            "ended_at": clock.now().isoformat(),
        }
    )
    return profile

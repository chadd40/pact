"""Derived progress / pace read-model for a pact.

Both surfaces (web dashboard + the living pact view, and the agent's narration)
render the same numbers, so they are computed once here from the pact + its
proofs rather than recomputed per client. Pure and side-effect-free.
"""

from __future__ import annotations

from datetime import datetime
from math import ceil

from pact.lifecycle import _valid_count  # single source of "what counts as valid"
from pact.models import Pact, Proof

_MILESTONES = (25, 50, 75, 100)


def compute_progress(pact: Pact, proofs: list[Proof], now: datetime) -> dict:
    """Return the derived progress block for a pact.

    Keys: valid_count, target, pct (0..100), days_left (>=0), on_track,
    behind, milestone (highest crossed of 25/50/75/100, else 0).
    """
    valid = _valid_count(pact, proofs)
    target = max(pact.target_count, 0)
    pct = min(100, round(100 * valid / target)) if target else 0

    secs_left = (pact.deadline_at - now).total_seconds()
    days_left = max(0, ceil(secs_left / 86400)) if secs_left > 0 else 0

    # Pace: compare progress against the linear expectation for elapsed time.
    start = pact.started_at or pact.created_at
    span = (pact.deadline_at - start).total_seconds()
    elapsed_frac = 1.0 if span <= 0 else min(1.0, max(0.0, (now - start).total_seconds() / span))
    expected = target * elapsed_frac
    on_track = valid >= expected
    behind = (not on_track) and valid < target

    milestone = max((m for m in _MILESTONES if pct >= m), default=0)

    return {
        "valid_count": valid,
        "target": target,
        "pct": pct,
        "days_left": days_left,
        "on_track": on_track,
        "behind": behind,
        "milestone": milestone,
    }

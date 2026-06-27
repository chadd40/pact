"""Derived progress / pace read-model for a pact.

Both surfaces (web dashboard + the living pact view, and the agent's narration)
render the same numbers, so they are computed once here from the pact + its
proofs rather than recomputed per client. Pure and side-effect-free.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from math import ceil

from pact.models import Pact, Proof, ProofStatus
from pact.lifecycle import _valid_count  # single source of "what counts as valid"

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


def derive_cadence(pact: Pact) -> tuple[int, int]:
    """Return (days_per_week, weeks) for a pact.

    Uses the stored values when present; otherwise reconstructs them from the
    deadline span and target so pre-cadence rows still read "N days a week for
    M weeks". weeks ~= span / 7d; days_per_week ~= target / weeks (both >= 1).
    """
    if pact.weeks and pact.weeks > 0:
        weeks = pact.weeks
    else:
        span_days = (pact.deadline_at - pact.created_at).total_seconds() / 86400
        weeks = max(1, round(span_days / 7)) if span_days > 0 else 1
    if pact.days_per_week and pact.days_per_week > 0:
        dpw = pact.days_per_week
    else:
        dpw = max(1, round(pact.target_count / weeks)) if weeks else max(1, pact.target_count)
    return dpw, weeks


def compute_cadence(pact: Pact, proofs: list[Proof], now: datetime) -> dict:
    """The weekly read-model the per-pact detail card renders.

    Keys: days_per_week, weeks, week_number (1..weeks), this_week_valid,
    this_week_target. "This week" is the 7-day window the pact is currently in,
    measured from started_at/created_at; this_week_valid counts distinct valid
    days (or passed proofs when distinct_days is off) inside that window.
    """
    dpw, weeks = derive_cadence(pact)
    start = pact.started_at or pact.created_at

    elapsed_days = (now - start).total_seconds() / 86400
    week_number = min(weeks, max(1, int(elapsed_days // 7) + 1)) if elapsed_days >= 0 else 1
    # If the deadline has passed, we're conceptually in the final week.
    if now >= pact.deadline_at:
        week_number = weeks

    wk_start = start + timedelta(days=(week_number - 1) * 7)
    wk_end = wk_start + timedelta(days=7)
    in_window = [
        p for p in proofs
        if p.status == ProofStatus.passed and wk_start <= p.received_at < wk_end
    ]
    if pact.distinct_days:
        this_week_valid = len({p.day_bucket for p in in_window})
    else:
        this_week_valid = len(in_window)

    return {
        "days_per_week": dpw,
        "weeks": weeks,
        "week_number": week_number,
        "this_week_valid": this_week_valid,
        "this_week_target": dpw,
    }

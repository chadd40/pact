from __future__ import annotations

import hashlib
import math

from pact.anticheat import count_distinct_valid_days
from pact.charities import get_charity
from pact.clock import Clock
from pact.models import CoachingMessage, Pact, PactStatus, Proof, TaskType
from pact.reasoning import ReasoningProvider, make_reasoning_task


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _days_left(pact: Pact, clock: Clock) -> int:
    """Whole days remaining until the pact deadline, clamped to 0.

    Uses integer division (floor) so that a deadline "tomorrow at 23:59"
    from "today at 18:00" (about 30 hours away) reads as 1 day left, not 2.
    This aligns with the nudge-governor's deadline_eve check (days_left <= 1).
    """
    seconds_left = (pact.deadline_at - clock.now()).total_seconds()
    return max(0, int(seconds_left // 86400))


def _message_id(pact_id: str, direction: str, trigger: str, body: str, sent_iso: str) -> str:
    """Deterministic message id from the parts that make a message unique."""
    seed = f"{pact_id}:{direction}:{trigger}:{sent_iso}:{body}"
    return "msg_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]


def donation_nag_message(pact: Pact, clock: Clock, charity_name: str) -> CoachingMessage:
    """A standing reminder to resolve a missed pact's donation. Part of
    'nag until resolved': the agent re-surfaces this until the owner approves the
    charge in Link or explicitly declines. Trigger 'donation_pending'.
    """
    now = clock.now()
    dollars = pact.stake_amount_cents / 100
    body = (
        f'You came up short on "{pact.title}", so ${dollars:.0f} is owed to '
        f"{charity_name}. Approve the donation in Link to honor your pact — or "
        f"decline it. It stays open until you resolve it."
    )
    return CoachingMessage(
        id=_message_id(pact.id, "outbound", "donation_pending", body, now.isoformat()),
        pact_id=pact.id,
        direction="outbound",
        trigger="donation_pending",
        pact_state_snapshot={"status": pact.status.value, "stake_cents": pact.stake_amount_cents},
        channel="web",
        body=body,
        sent_at=now,
    )


def failed_dispute_message(pact: Pact, clock: Clock) -> CoachingMessage:
    """Fired once at the moment a pact fails: tell the user they missed and have
    until the dispute window closes to contest it. Without this the 24h window
    elapses silently and the dispute feature is unreachable. Trigger 'failed'."""
    now = clock.now()
    deadline = pact.dispute_window_closes_at
    when = deadline.isoformat() if deadline is not None else "soon"
    dollars = pact.stake_amount_cents / 100
    body = (
        f'You came up short on "{pact.title}". You have until {when} to dispute — '
        f"send more proof if this is wrong. Otherwise ${dollars:.0f} goes to your charity."
    )
    return CoachingMessage(
        id=_message_id(pact.id, "outbound", "failed", body, now.isoformat()),
        pact_id=pact.id,
        direction="outbound",
        trigger="failed",
        pact_state_snapshot={"status": pact.status.value, "stake_cents": pact.stake_amount_cents},
        channel="web",
        body=body,
        sent_at=now,
    )


def renew_message(pact: Pact, clock: Clock) -> CoachingMessage:
    """Fired once when a pact reaches a terminal outcome (succeeded or, after a
    miss, donation_complete): congratulate / re-motivate and prompt a new pact to
    keep the momentum. Trigger 'renew'."""
    now = clock.now()
    if pact.status == PactStatus.succeeded:
        body = (
            f'You kept "{pact.title}" — nice work. Keep the momentum going: '
            "want to start another pact?"
        )
    else:  # donation_complete -- paid after a miss
        body = (
            f'"{pact.title}" cost you this time, but the donation is done. '
            "Let's get the next one — ready to make a new pact?"
        )
    return CoachingMessage(
        id=_message_id(pact.id, "outbound", "renew", body, now.isoformat()),
        pact_id=pact.id,
        direction="outbound",
        trigger="renew",
        pact_state_snapshot={"status": pact.status.value},
        channel="web",
        body=body,
        sent_at=now,
    )


# ---------------------------------------------------------------------------
# Task 4: pace()
# ---------------------------------------------------------------------------

def pace(pact: Pact, proofs: list[Proof], clock: Clock) -> dict:
    """Read-only pace math for coaching and the Active screen.

    Returns a dict with keys:
      valid     – distinct valid (passed) days proven so far
      target    – the pact's required distinct-day count
      days_left – whole days until the deadline, floored, never negative
      needed    – remaining distinct days required, never negative
      on_pace   – True when the remaining days are enough to cover what's still needed
    """
    valid = count_distinct_valid_days(proofs)
    target = pact.target_count
    days_left = _days_left(pact, clock)
    needed = max(target - valid, 0)
    on_pace = needed <= days_left

    return {
        "valid": valid,
        "target": target,
        "days_left": days_left,
        "needed": needed,
        "on_pace": on_pace,
    }


# ---------------------------------------------------------------------------
# Task 5: should_nudge() — nag-governor
# ---------------------------------------------------------------------------

def should_nudge(
    pact: Pact,
    proofs: list[Proof],
    messages: list[CoachingMessage],
    clock: Clock,
    nudge_hour: int = 0,
) -> str | None:
    """Decide whether (and which) nudge trigger to fire.

    Returns None (suppress) or one of: "behind_pace" | "deadline_eve" | "mid_week".

    Nag-governor rules (in order):
    1. Only nudge active pacts.
    2. At most one outbound message per calendar day.
    3. Suppress if any proof was received today (regardless of status).
    4. Return trigger based on pace.
    """
    # Rule 1: active pacts only.
    if pact.status != PactStatus.active:
        return None

    today = clock.now().date()

    # Rule 2: at most one outbound per calendar day.
    for msg in messages:
        if msg.direction == "outbound" and msg.sent_at.date() == today:
            return None

    # Rule 3: suppress if any proof landed today (any status counts).
    for proof in proofs:
        if proof.received_at.date() == today:
            return None

    # Rule 3b: time-of-day gate -- only fire at/after nudge_hour in the pact's local
    # timezone, so the daily reminder lands ~5pm local rather than at the first
    # post-midnight tick. nudge_hour=0 (default) disables the gate.
    if nudge_hour > 0:
        from zoneinfo import ZoneInfo

        try:
            local = clock.now().astimezone(ZoneInfo(pact.timezone))
        except Exception:
            local = clock.now()
        if local.hour < nudge_hour:
            return None

    # Rule 4: compute pace and return the appropriate trigger.
    p = pace(pact, proofs, clock)
    if not p["on_pace"]:
        return "behind_pace"
    if p["days_left"] <= 1:
        return "deadline_eve"
    return "mid_week"


# ---------------------------------------------------------------------------
# Task 6: generate_coach_message() + user_reply()
# ---------------------------------------------------------------------------

def generate_coach_message(
    pact: Pact,
    proofs: list[Proof],
    trigger: str,
    provider: ReasoningProvider,
    clock: Clock,
    charity_name: str,
) -> CoachingMessage:
    """Generate an outbound coaching message via the reasoning provider.

    Builds a snapshot of the current pace state, calls the provider with
    TaskType.coach, and wraps the result in a CoachingMessage with a
    deterministic id.
    """
    valid = count_distinct_valid_days(proofs)
    days_left = _days_left(pact, clock)
    snapshot = {"valid": valid, "target": pact.target_count, "days_left": days_left}

    task = make_reasoning_task(
        TaskType.coach,
        pact.id,
        {
            "valid": valid,
            "target": pact.target_count,
            "days_left": days_left,
            "charity": charity_name,
            "title": pact.title,
            "goal": pact.goal,
            "agent": pact.agent or "Hermes",
            "stake_cents": pact.stake_amount_cents,
            "status": pact.status.value,
        },
        clock,
    )
    result = provider.resolve(task)
    body = str(result["message"])
    now = clock.now()

    return CoachingMessage(
        id=_message_id(pact.id, "outbound", trigger, body, now.isoformat()),
        pact_id=pact.id,
        direction="outbound",
        trigger=trigger,
        pact_state_snapshot=snapshot,
        channel="web",
        body=body,
        sent_at=now,
    )


def user_reply(
    pact: Pact,
    text: str,
    proofs: list[Proof],
    provider: ReasoningProvider,
    clock: Clock,
    attachments: list[dict] | None = None,
) -> tuple[CoachingMessage, CoachingMessage]:
    """Persist a user's inbound reply and generate an outbound coach response.

    Returns (inbound, outbound) as a tuple of CoachingMessages. The inbound
    carries the user's text verbatim; the outbound is a conversational coach
    response generated via the reasoning provider, grounded in the pact's real
    pace (distinct valid days proven so far) rather than a fixed zero.
    """
    now = clock.now()
    attachment_meta = attachments or []

    # Inbound: the user's own message.
    inbound = CoachingMessage(
        id=_message_id(pact.id, "inbound", "reply", text, now.isoformat()),
        pact_id=pact.id,
        direction="inbound",
        trigger="reply",
        pact_state_snapshot={},
        channel="web",
        body=text,
        sent_at=now,
        attachments=attachment_meta,
    )

    # Outbound: coach response grounded in the real distinct-valid-day count.
    valid = count_distinct_valid_days(proofs)
    days_left = _days_left(pact, clock)
    # Human charity name (not the raw id) so the coach prose reads naturally;
    # fall back to the id only if the charity is unknown. Mirrors the name passed
    # into generate_coach_message() so both coach paths read the same.
    charity_name = (get_charity(pact.charity_id) or {}).get("name", pact.charity_id)
    task = make_reasoning_task(
        TaskType.coach,
        pact.id,
        {
            "valid": valid,
            "target": pact.target_count,
            "days_left": days_left,
            "charity": charity_name,
            "title": pact.title,
            "goal": pact.goal,
            "agent": pact.agent or "Hermes",
            "stake_cents": pact.stake_amount_cents,
            "status": pact.status.value,
            "user_message": text,
            "attachments": attachment_meta,
        },
        clock,
    )
    result = provider.resolve(task)
    reply_body = str(result["message"])

    outbound = CoachingMessage(
        id=_message_id(pact.id, "outbound", "reply", reply_body, now.isoformat()),
        pact_id=pact.id,
        direction="outbound",
        trigger="reply",
        pact_state_snapshot={
            "valid": valid,
            "target": pact.target_count,
            "days_left": days_left,
        },
        channel="web",
        body=reply_body,
        sent_at=now,
    )

    return inbound, outbound

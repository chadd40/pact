from __future__ import annotations

from datetime import datetime, timedelta

from pact.anticheat import day_bucket
from pact.clock import Clock, FixedClock
from pact.config import Settings
from pact.lifecycle import close_dispute_window, reconcile_on_startup, settle
from pact.models import (
    Modality,
    Pact,
    PactStatus,
    Proof,
    ProofStatus,
    Rubric,
    StakeState,
)
from pact.payment import PaymentProvider, TestLinkProvider
from pact.repository import Repository

_TIMEZONE = "America/Los_Angeles"
_CHARITY_ID = "world_central_kitchen"
_CHARITY_URL = "https://wck.org/donate"
_STAKE_CENTS = 500


def _rubric() -> Rubric:
    return Rubric(
        modality=Modality.photo,
        require_token=True,
        must_show=["clear evidence the committed action was performed"],
        reject_if=["stock/watermark", "pure UI screenshot", "missing token"],
        min_distinct_days=5,
        count_target=5,
        rest_if_injured_counts=True,
        rigor_floor={
            "require_token": True,
            "min_distinct_days": 4,
            "non_negotiable": ["require_token", "server_time_is_truth", "no_duplicates"],
        },
    )


def _make_pact(
    pact_id: str,
    title: str,
    goal: str,
    deadline_at: datetime,
    created_at: datetime,
) -> Pact:
    return Pact(
        id=pact_id,
        owner="demo@pact.local",
        original_prompt="work out 5x this week or $5 to charity",
        title=title,
        goal=goal,
        timezone=_TIMEZONE,
        deadline_at=deadline_at,
        target_count=5,
        distinct_days=True,
        recommended_stake_cents=_STAKE_CENTS,
        stake_amount_cents=_STAKE_CENTS,
        charity_id=_CHARITY_ID,
        charity_url=_CHARITY_URL,
        rubric=_rubric(),
        status=PactStatus.active,
        stake_state=StakeState.committed,
        created_at=created_at,
        started_at=created_at,
    )


def _passed_proof(pact_id: str, idx: int, received_at: datetime) -> Proof:
    return Proof(
        id=f"proof-{pact_id}-{idx}",
        pact_id=pact_id,
        modality=Modality.photo,
        received_at=received_at,
        day_bucket=day_bucket(received_at, _TIMEZONE),
        token_issued=f"PACT-{idx:02d}",
        token_ok=True,
        status=ProofStatus.passed,
        judge_reason="Token verified, content satisfies rubric, no duplicate.",
        judge_checklist={"token": True, "content": True, "not_dup": True},
    )


def seed(repo: Repository, clock: Clock, settings: Settings) -> dict:
    """Build three deterministic demo pacts (WIN / FAIL / LIVE) and persist them.

    WIN: 5 passed proofs on 5 distinct days, then settled -> succeeded, $0 moved.
    FAIL: 4 passed proofs, deadline in the past, settled -> failed/donated.
    LIVE: active, deadline ~4 days ahead, 2 passed proofs on 2 distinct days.

    Stable ids ("pact-win"/"pact-fail"/"pact-live") so /demo/reset is repeatable.
    """
    now = clock.now()
    payment = TestLinkProvider()

    # ── WIN ───────────────────────────────────────────────────────────────────
    win = _make_pact(
        "pact-win",
        "Work out 5x this week (WIN)",
        "Complete the committed action on 5 distinct days.",
        deadline_at=now,
        created_at=now - timedelta(days=6),
    )
    win_proofs = [
        _passed_proof("pact-win", i, now - timedelta(days=5 - i, hours=3))
        for i in range(5)
    ]
    win, win_verdict = settle(win, win_proofs, clock, payment, settings)
    repo.save_pact(win)
    for proof in win_proofs:
        repo.save_proof(proof)
    repo.save_verdict(win_verdict)

    # ── FAIL ──────────────────────────────────────────────────────────────────
    fail = _make_pact(
        "pact-fail",
        "Work out 5x this week (FAIL)",
        "Complete the committed action on 5 distinct days.",
        deadline_at=now - timedelta(hours=1),
        created_at=now - timedelta(days=6),
    )
    fail_proofs = [
        _passed_proof("pact-fail", i, now - timedelta(days=5 - i, hours=3))
        for i in range(4)
    ]
    fail, fail_verdict = settle(fail, fail_proofs, clock, payment, settings)
    # The seeded FAIL pact's deadline is already in the past; close its dispute
    # window immediately so the demo shows a fully-resolved donated pact. Use a
    # clock advanced past the grace horizon ONLY for this deterministic close.
    fail_close_clock = FixedClock(
        now + timedelta(hours=settings.dispute_grace_hours + 1)
    )
    fail, fail_verdict = close_dispute_window(
        fail, fail_proofs, fail_close_clock, payment, settings
    )
    repo.save_pact(fail)
    for proof in fail_proofs:
        repo.save_proof(proof)
    repo.save_verdict(fail_verdict)

    # ── LIVE ──────────────────────────────────────────────────────────────────
    live = _make_pact(
        "pact-live",
        "Work out 5x this week (LIVE)",
        "Complete the committed action on 5 distinct days.",
        deadline_at=now + timedelta(days=4),
        created_at=now - timedelta(days=2),
    )
    live_proofs = [
        _passed_proof("pact-live", i, now - timedelta(days=1 - i, hours=3))
        for i in range(2)
    ]
    repo.save_pact(live)
    for proof in live_proofs:
        repo.save_proof(proof)

    return {"win": win.id, "fail": fail.id, "live": live.id}


def advance_day(
    repo: Repository,
    clock: Clock,
    payment: PaymentProvider,
    settings: Settings,
    hours: int = 24,
) -> dict:
    """Bump the demo clock, settle newly-due pacts, and close elapsed dispute windows.

    Demo-only: requires a FixedClock so the advance is deterministic and the same
    injected clock the scheduler reads moves forward. With a RealClock there is
    nothing to advance, so we refuse rather than silently no-op.

    Reports two buckets from the reconcile sweep: `settled` (pacts that just crossed
    their deadline into `failed` with an open dispute window — no money moved) and
    `donated` (pacts whose grace window just elapsed and whose deferred donation was
    executed this sweep).
    """
    if not isinstance(clock, FixedClock):
        raise ValueError(
            "advance_day requires a FixedClock (demo clock mode); "
            f"got {type(clock).__name__}"
        )
    clock.advance(hours=hours)
    changed = reconcile_on_startup(repo, clock, payment, settings)
    settled = [p.id for p in changed if p.status == PactStatus.failed]
    donated = [p.id for p in changed if p.status == PactStatus.donated]
    return {
        "now": clock.now().isoformat(),
        "settled": settled,
        "donated": donated,
    }


def reset(repo: Repository, clock: Clock, settings: Settings) -> dict:
    """Restore the three seeded pacts and rewind the demo clock to the seed instant.

    Wipes every table, rewinds a FixedClock to settings.demo_seed_iso (a RealClock
    can't be rewound, so it's left as-is), then reseeds. Stable ids make this
    repeatable for /demo/reset.
    """
    repo.reset_all()
    if isinstance(clock, FixedClock):
        clock.set(datetime.fromisoformat(settings.demo_seed_iso))
    return seed(repo, clock, settings)

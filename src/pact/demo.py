from __future__ import annotations

from datetime import datetime, timedelta

from pact.anticheat import day_bucket
from pact.charities import get_charity
from pact.clock import Clock, FixedClock
from pact.config import Settings
from pact.lifecycle import close_dispute_window, reconcile_on_startup, settle
from pact.models import (
    CoachingMessage,
    Modality,
    Pact,
    PactStatus,
    Profile,
    Proof,
    ProofStatus,
    Rubric,
    StakeState,
)
from pact.payment import PaymentProvider, TestLinkProvider
from pact.repository import Repository

_OWNER = "colehaddad40@gmail.com"

_TIMEZONE = "America/Los_Angeles"
_CHARITY_ID = "against_malaria_foundation"
_CHARITY_URL = "https://againstmalaria.com/donate"
_STAKE_CENTS = 1000


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
        owner="colehaddad40@gmail.com",
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


def _coaching_message(
    msg_id: str,
    pact_id: str,
    trigger: str,
    body: str,
    sent_at: datetime,
    snapshot: dict,
) -> CoachingMessage:
    """An outbound, undelivered coach nudge with a stable id (repeatable reset)."""
    return CoachingMessage(
        id=msg_id,
        pact_id=pact_id,
        direction="outbound",
        trigger=trigger,
        pact_state_snapshot=snapshot,
        channel="web",
        body=body,
        sent_at=sent_at,
        delivered_at=None,
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

    # Seed visible coaching activity on the LIVE pact so the coach pane and the
    # outbox are alive immediately after Seed. Outbound + undelivered so they
    # surface in repo.outbox(owner). Stable ids -> /demo/reset overwrites in place.
    live_snapshot = {"valid": 2, "target": live.target_count, "days_left": 4}
    coaching = [
        _coaching_message(
            "coach-live-mid_week",
            live.id,
            "mid_week",
            "Midway check-in: 2 of 5 days logged. Nice start — keep the streak going.",
            now - timedelta(days=1, hours=2),
            live_snapshot,
        ),
        _coaching_message(
            "coach-live-behind_pace",
            live.id,
            "behind_pace",
            "Heads up: you're a touch behind pace with 4 days left. One session today "
            "keeps your stake with you instead of the Against Malaria Foundation.",
            now - timedelta(hours=2),
            live_snapshot,
        ),
    ]
    for msg in coaching:
        repo.save_coaching_message(msg)

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


# ─── Showcase seeds (app-shell demo) ──────────────────────────────────────────
# Layered on by the /demo endpoints AFTER seed()/reset() so the live app exercises
# every Home + Detail state: a fuller active carousel, an under-review pact, a
# donation-pending pact (drives the nag banner + the Link approval flow), a failed
# pact with an open dispute window, and a closed ledger. Kept OUT of seed()/reset()
# so the unit-tested "exactly three pacts" contract is untouched. Stable ids →
# repeatable across reseeds.


def _rubric_for(target: int) -> Rubric:
    mdd = min(max(target - 1, 1), max(target, 1))
    return Rubric(
        modality=Modality.photo,
        require_token=True,
        must_show=["clear evidence the committed action was performed"],
        reject_if=["stock/watermark", "pure UI screenshot", "missing token"],
        min_distinct_days=mdd,
        count_target=target,
        rest_if_injured_counts=True,
        rigor_floor={"require_token": True, "min_distinct_days": mdd},
    )


def _ambiguous_proof(pact_id: str, idx: int, received_at: datetime) -> Proof:
    return Proof(
        id=f"proof-{pact_id}-{idx}",
        pact_id=pact_id,
        modality=Modality.photo,
        received_at=received_at,
        day_bucket=day_bucket(received_at, _TIMEZONE),
        token_issued=f"PACT-{idx:02d}",
        token_ok=True,
        status=ProofStatus.ambiguous,
        judge_reason="Token verified but content is a judgment call — sent for review.",
        judge_checklist={"token": True, "content": None, "not_dup": True},
    )


def _showcase_pact(
    pact_id: str,
    title: str,
    status: PactStatus,
    *,
    dpw: int,
    weeks: int,
    stake: int,
    charity_id: str,
    created: datetime,
    deadline: datetime,
    stake_state: StakeState = StakeState.committed,
    spend_request_id: str | None = None,
    dispute_window_closes_at: datetime | None = None,
    verdict_at: datetime | None = None,
) -> Pact:
    charity = get_charity(charity_id)
    charity_url = charity["donation_url"] if charity else ""
    target = dpw * weeks
    return Pact(
        id=pact_id,
        owner=_OWNER,
        original_prompt=title,
        title=title,
        goal=f"Complete the committed action {target} times across {target} distinct days.",
        timezone=_TIMEZONE,
        deadline_at=deadline,
        target_count=target,
        distinct_days=True,
        days_per_week=dpw,
        weeks=weeks,
        recommended_stake_cents=stake,
        stake_amount_cents=stake,
        charity_id=charity_id,
        charity_url=charity_url,
        agent="Hermes",
        rubric=_rubric_for(target),
        status=status,
        stake_state=stake_state,
        spend_request_id=spend_request_id,
        created_at=created,
        started_at=created,
        verdict_at=verdict_at,
        dispute_window_closes_at=dispute_window_closes_at,
    )


def seed_states(repo: Repository, clock: Clock, settings: Settings) -> dict:
    """Persist the showcase pacts that exercise every app-shell state. Returns the
    map of state -> pact_id (the States/Demo menu deep-links to these)."""
    now = clock.now()
    out: dict[str, str] = {}

    def _passes(pact_id: str, n: int, end: datetime) -> None:
        for i in range(n):
            repo.save_proof(_passed_proof(pact_id, i, end - timedelta(days=n - i, hours=3)))

    # ── Active carousel pacts (besides the LIVE one from seed()) ───────────────
    actives = [
        # id, title, dpw, weeks, stake, charity, created_days_ago, deadline_in_days, passed
        ("pact-read", "Read 20 minutes", 5, 2, 7500, "donorschoose", 5, 9, 4),
        ("pact-meditate", "Meditate", 4, 3, 6000, "charity_water", 3, 18, 3),
        ("pact-phone", "No phone after 10pm", 6, 2, 5000, "feeding_america", 6, 8, 2),
    ]
    for pid, title, dpw, weeks, stake, charity, cago, din, passed in actives:
        p = _showcase_pact(
            pid, title, PactStatus.active, dpw=dpw, weeks=weeks, stake=stake,
            charity_id=charity, created=now - timedelta(days=cago),
            deadline=now + timedelta(days=din),
        )
        repo.save_pact(p)
        _passes(pid, passed, now)
    out["active"] = "pact-read"

    # ── Under review: shortfall with an ambiguous proof that could still lift ──
    review = _showcase_pact(
        "pact-review", "Cold plunge", PactStatus.needs_review, dpw=5, weeks=1,
        stake=9000, charity_id="unicef", created=now - timedelta(days=6),
        deadline=now - timedelta(hours=1), verdict_at=now - timedelta(hours=1),
    )
    repo.save_pact(review)
    for i in range(3):
        repo.save_proof(_passed_proof("pact-review", i, now - timedelta(days=5 - i, hours=3)))
    repo.save_proof(_ambiguous_proof("pact-review", 3, now - timedelta(hours=2)))
    out["review"] = "pact-review"

    # ── Donation pending: window already closed, no money moved → Link flow. ───
    donate = _showcase_pact(
        "pact-donate", "Wake at 6am", PactStatus.donation_pending, dpw=5, weeks=1,
        stake=20000, charity_id="save_the_children", created=now - timedelta(days=8),
        deadline=now - timedelta(days=2), verdict_at=now - timedelta(days=1),
        dispute_window_closes_at=now - timedelta(days=1),
    )
    repo.save_pact(donate)
    for i in range(2):
        repo.save_proof(_passed_proof("pact-donate", i, now - timedelta(days=7 - i, hours=3)))
    out["donation"] = "pact-donate"

    # ── Failed with an OPEN dispute window → verdict-failed + live countdown. ──
    miss = _showcase_pact(
        "pact-miss", "Write daily", PactStatus.failed, dpw=5, weeks=1,
        stake=12000, charity_id="feeding_america", created=now - timedelta(days=6),
        deadline=now - timedelta(hours=1), verdict_at=now - timedelta(hours=1),
        dispute_window_closes_at=now + timedelta(hours=2),
    )
    repo.save_pact(miss)
    for i in range(3):
        repo.save_proof(_passed_proof("pact-miss", i, now - timedelta(days=5 - i, hours=3)))
    out["failed"] = "pact-miss"

    # ── Closed ledger: kept (succeeded) + missed (donated). ────────────────────
    closed = [
        # id, title, status, stake, charity, ended_days_ago, stake_state, spend_request_id
        ("pact-10k", "Ran a 10K", PactStatus.succeeded, 15000, "charity_water", 40, StakeState.released, None),
        ("pact-dryjan", "Dry January", PactStatus.succeeded, 30000, "feeding_america", 30, StakeState.released, None),
        ("pact-sketch", "Sketch daily", PactStatus.succeeded, 7500, "donorschoose", 20, StakeState.released, None),
        ("pact-sugar", "No sugar", PactStatus.donated, 20000, "feeding_america", 25, StakeState.executed, "test_sr_pact-sugar_20000"),
        ("pact-inbox", "Inbox zero by 6", PactStatus.donated, 15000, "unicef", 18, StakeState.executed, "test_sr_pact-inbox_15000"),
    ]
    for pid, title, status, stake, charity, dago, sstate, spend in closed:
        deadline = now - timedelta(days=dago)
        p = _showcase_pact(
            pid, title, status, dpw=5, weeks=1, stake=stake, charity_id=charity,
            created=deadline - timedelta(days=7), deadline=deadline,
            stake_state=sstate, spend_request_id=spend, verdict_at=deadline,
        )
        repo.save_pact(p)
        _passes(pid, 5 if status == PactStatus.succeeded else 3, deadline)

    # ── Owner track record so the Home stats read true. ────────────────────────
    repo.save_profile(
        Profile(
            owner=_OWNER,
            current_streak=4,
            best_streak=9,
            kept=12,
            failed=3,
            pact_ids=[],
            history=[],
        )
    )

    return out

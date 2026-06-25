from __future__ import annotations

import hashlib
from datetime import datetime

from pact.models import Pact, PactStatus


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

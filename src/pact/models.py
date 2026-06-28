from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, field_validator


class PactStatus(str, Enum):
    draft = "draft"
    active = "active"
    evaluating = "evaluating"
    succeeded = "succeeded"
    failed = "failed"
    needs_review = "needs_review"
    canceled_release = "canceled_release"
    canceled_forfeit = "canceled_forfeit"
    donation_pending = "donation_pending"
    donated = "donated"
    donation_failed = "donation_failed"
    donation_declined = "donation_declined"


class StakeState(str, Enum):
    none = "none"
    committed = "committed"
    executing = "executing"
    executed = "executed"
    released = "released"
    declined = "declined"
    error = "error"


class ProofStatus(str, Enum):
    passed = "passed"
    failed = "failed"
    ambiguous = "ambiguous"


class Modality(str, Enum):
    photo = "photo"
    log = "log"
    url = "url"
    file = "file"
    text = "text"


class TaskType(str, Enum):
    draft = "draft"
    judge_proof = "judge_proof"
    coach = "coach"
    verdict = "verdict"


class TaskStatus(str, Enum):
    pending = "pending"
    claimed = "claimed"
    done = "done"
    failed = "failed"


class PaymentAction(str, Enum):
    none = "none"
    donation_executed = "donation_executed"
    donation_failed = "donation_failed"
    donation_declined = "donation_declined"
    cancelled = "cancelled"


class Rubric(BaseModel):
    modality: Modality
    require_token: bool = True
    must_show: list[str]
    reject_if: list[str] = []
    min_distinct_days: int
    count_target: int
    rest_if_injured_counts: bool = True
    rigor_floor: dict = {}


class Pact(BaseModel):
    id: str
    owner: str
    original_prompt: str
    title: str
    goal: str
    timezone: str
    deadline_at: datetime
    target_count: int
    distinct_days: bool = True
    # The weekly cadence the pact was built from (days_per_week x weeks = target_count).
    # Stored so every surface speaks the same "N days a week for M weeks" language the
    # Create flow collects. Optional/nullable: pre-cadence rows derive it on read
    # (see pact.progress.compute_cadence).
    days_per_week: int | None = None
    weeks: int | None = None
    recommended_stake_cents: int
    stake_amount_cents: int
    currency: str = "usd"
    charity_id: str
    charity_url: str
    agent: str | None = None
    card_art: str | None = None
    signer_name: str | None = None
    proof_source: str = "manual"
    freezes_allowed: int = 1
    freezes_used: int = 0
    freeze_extension_hours: int = 24
    rubric: Rubric
    status: PactStatus = PactStatus.draft
    stake_state: StakeState = StakeState.none
    spend_request_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    verdict_at: datetime | None = None
    dispute_window_closes_at: datetime | None = None

    @field_validator("stake_amount_cents")
    @classmethod
    def _check_stake(cls, v: int) -> int:
        if not (0 < v <= 50000):
            raise ValueError("stake_amount_cents must satisfy 0 < v <= 50000")
        return v


class Proof(BaseModel):
    id: str
    pact_id: str
    modality: Modality
    received_at: datetime
    day_bucket: str
    token_issued: str | None = None
    token_ok: bool = False
    phash: str | None = None
    dup_of: str | None = None
    artifact_path: str | None = None
    status: ProofStatus
    judge_reason: str = ""
    judge_checklist: dict = {}


class Verdict(BaseModel):
    pact_id: str
    status: PactStatus
    valid_proof_count: int
    target_count: int
    freezes_used: int
    summary: str
    proof_ids: list[str]
    payment_action: PaymentAction = PaymentAction.none
    payment_ref: str | None = None
    receipt_artifact_path: str | None = None
    honesty_note: str


class ReasoningTask(BaseModel):
    id: str
    pact_id: str | None
    type: TaskType
    required_capability: str | None = None
    input: dict
    status: TaskStatus = TaskStatus.pending
    result: dict | None = None
    claimed_by: str | None = None
    created_at: datetime


class Profile(BaseModel):
    owner: str
    pact_ids: list[str] = []
    current_streak: int = 0
    best_streak: int = 0
    kept: int = 0
    failed: int = 0
    history: list[dict] = []


class LinkAccount(BaseModel):
    """A per-owner Link funding connection. Pact never holds money (no escrow);
    'connected' only means a funding source is registered so a charge CAN fire
    on failure. The funding_ref here is a safe deterministic TEST reference."""

    owner: str
    connected: bool = False
    funding_ref: str | None = None
    connected_at: datetime | None = None


class AccountLink(BaseModel):
    """Ties an external agent to an owner's Pact account. STUB seam for real
    multi-user agent auth — the token is deterministic per owner and carries no
    real secret/rotation/expiry today (the app is single-owner / local-first)."""

    owner: str
    token: str
    created_at: datetime | None = None


class CoachingMessage(BaseModel):
    id: str
    pact_id: str
    direction: str
    trigger: str
    pact_state_snapshot: dict = {}
    channel: str = "web"
    body: str
    sent_at: datetime
    delivered_at: datetime | None = None

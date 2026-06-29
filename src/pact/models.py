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
    on failure. In test mode the funding_ref is deterministic; in live mode it is
    a non-secret Link payment-method id."""

    owner: str
    connected: bool = False
    funding_ref: str | None = None
    connected_at: datetime | None = None
    payment_method_id: str | None = None
    payment_method_label: str | None = None
    payment_method_last4: str | None = None
    auth_status: str | None = None
    checked_at: datetime | None = None
    error: str | None = None


class PaymentAttempt(BaseModel):
    """Durable audit row for a Link/payment-provider attempt.

    This records what Pact asked the provider to do. It deliberately stores
    provider references and status, not payment credentials.
    """

    id: str
    pact_id: str
    owner: str
    provider: str
    mode: str
    status: str
    amount_cents: int
    currency: str
    charity_id: str
    merchant_name: str
    merchant_url: str
    idempotency_key: str
    provider_ref: str | None = None
    approval_status: str | None = None
    created_at: datetime
    updated_at: datetime
    error: str | None = None


class DonationReceipt(BaseModel):
    """Evidence that the charity payout landed, distinct from provider approval."""

    pact_id: str
    receipt_status: str
    receipt_source: str | None = None
    receipt_ref: str | None = None
    receipt_url: str | None = None
    receipt_artifact_path: str | None = None
    confirmed_at: datetime | None = None
    confirmation_notes: str | None = None


class ProofReview(BaseModel):
    """Durable audit row for an agent/human proof judgment."""

    id: str
    proof_id: str
    pact_id: str
    reviewer: str
    capabilities: list[str] = []
    input_artifacts: dict = {}
    status: ProofStatus
    reason: str
    checklist: dict = {}
    created_at: datetime


class AgentSession(BaseModel):
    """Ties an external agent to an owner's Pact account.

    Only token hashes are persisted. The raw token is returned once at mint time
    and must never be written to the database or serialized model rows.
    """

    owner: str
    token_hash: str
    token_prefix: str
    created_at: datetime | None = None
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    scopes: list[str] = []


class AccountLink(AgentSession):
    """Backward-compatible name for the app's connect-your-agent row."""


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
    attachments: list[dict] = []

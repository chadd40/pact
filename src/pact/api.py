from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from pact import broker
from pact.accounts import hash_token, link_for
from pact.anticheat import TokenStore
from pact.charities import CHARITIES, all_charity_ids, get_charity, is_allowed_url
from pact.clock import Clock, FixedClock
from pact.coaching import generate_coach_message, user_reply
from pact.config import Settings
from pact.connectors import build_connector_health
from pact.demo import advance_day as demo_advance_day
from pact.demo import reset as demo_reset
from pact.demo import seed as demo_seed
from pact.demo import seed_states as demo_seed_states
from pact.lifecycle import (
    PactRefused,
    TransitionError,
    cancel,
    close_dispute_window,
    confirm_and_start,
    confirm_stake,
    create_pact_structured,
    decline_donation,
    draft_pact,
    execute_forfeit_donation,
    finalize_donation,
    new_pact_id,
    resolve_via_link,
    settle,
    spend_freeze,
    submit_dispute,
    submit_proof,
    terminal_verdict,
    transition,
)
from pact.guardrails import build_spend_guard
from pact.spend_policy import SpendRequest
from pact.images import save_proof_image, strip_exif
from pact.link import connect_account, is_owner_connected, new_account, refresh_live_account
from pact.models import (
    AgentSession,
    DonationReceipt,
    Modality,
    Pact,
    PactStatus,
    Profile,
    Proof,
    ProofReview,
    StakeState,
    TaskType,
)
from pact.packet import build_packet
from pact.payment import (
    LinkChargeAmbiguous,
    PaymentProvider,
    RecordingPaymentProvider,
    payment_status_is_approved,
    payment_status_is_denied,
    payment_status_is_expired,
    read_card_secret,
)
from pact.progress import compute_cadence, compute_progress
from pact.profile import record_outcome
from pact.reasoning import ReasoningProvider
from pact.repository import Repository
from pact.scheduler import tick as scheduler_tick

# Statuses at which a pact's outcome is genuinely FINAL and safe to fold into
# the owner's streak/history. Deliberately excludes `failed`: under the Day-3
# pre-donation dispute window a `failed` pact has NOT moved money and can still
# be overturned to `succeeded` within the window, so recording it early would
# wrongly (and irreversibly, first-write-wins) stamp a failure. Donation/forfeit
# states below are reached only after the window closes. Mirrors scheduler.tick.
ALLOWED_CARD_ART = frozenset(f"/create/create_{i}.png" for i in range(1, 6))

_TERMINAL_STATUSES = {
    PactStatus.succeeded,
    # donation_pending is reached only AFTER the dispute window closes (no more
    # overturns), so it's a finalized miss: record the failure now even though the
    # human-approved donation is still being nagged toward resolution.
    PactStatus.donation_pending,
    PactStatus.donated,
    PactStatus.donation_failed,
    PactStatus.donation_declined,
    PactStatus.canceled_forfeit,
}

_RECEIPT_STATUSES = {
    "manual_receipt",
    "provider_confirmed",
    "failed_or_reversed",
}


def _safe_attachment_name(filename: str | None, fallback: str) -> str:
    raw = Path(filename or fallback).name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(".-")
    return safe or fallback


async def _read_coach_payload(
    request: Request,
    pact_id: str,
    settings: Settings,
    clock: Clock,
) -> tuple[str, list[dict]]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=422, detail="invalid coach message payload")
        body = CoachIn.model_validate(payload)
        return body.message, []

    form = await request.form()
    message = str(form.get("message") or "")
    uploads = form.getlist("attachments")
    attachments: list[dict] = []
    stamp = clock.now().strftime("%Y%m%d%H%M%S")
    out_dir = Path(settings.artifacts_dir) / pact_id / "coach"
    out_dir.mkdir(parents=True, exist_ok=True)

    for index, upload in enumerate(uploads):
        if not hasattr(upload, "read"):
            continue
        data = await upload.read()
        filename = _safe_attachment_name(
            getattr(upload, "filename", None),
            f"attachment-{index + 1}",
        )
        artifact_path = out_dir / f"{stamp}-{index}-{filename}"
        with open(artifact_path, "wb") as f:
            f.write(data)
        attachments.append({
            "filename": filename,
            "content_type": getattr(upload, "content_type", None),
            "size_bytes": len(data),
            "artifact_path": os.fspath(artifact_path),
        })
    if not message.strip() and attachments:
        count = len(attachments)
        message = f"Attached {count} file{'s' if count != 1 else ''}."
    if not message.strip():
        raise HTTPException(status_code=422, detail="message is required")
    return message, attachments


class DraftIn(BaseModel):
    prompt: str


class ConfirmIn(BaseModel):
    pact_id: str
    stake_amount_cents: int
    charity_id: str
    consent_acknowledged: bool = False


class ProofIn(BaseModel):
    modality: Modality
    token: str
    content_ok: bool = True
    image_path: str | None = None


class OwnerIn(BaseModel):
    owner: str


class CoachIn(BaseModel):
    message: str


class CreateIn(BaseModel):
    goal_title: str
    goal_template: str | None = None
    days_per_week: int
    weeks: int
    stake_amount_cents: int
    charity_id: str
    agent: str | None = None
    consent_acknowledged: bool = False
    owner: str | None = None
    # Custom goals: the owner's own "what counts as a check-in" definition.
    description: str | None = None
    card_art: str | None = None
    # The name the owner signed when sealing the pact (free text, shown on the
    # editorial card back). Capped to a sane length.
    signer_name: str | None = Field(default=None, max_length=80)


class EnqueueTaskIn(BaseModel):
    type: TaskType
    input: dict
    required_capability: str | None = None


class ClaimTaskIn(BaseModel):
    agent_name: str
    capabilities: list[str]


class TaskResultIn(BaseModel):
    result: dict


class LinkConnectIn(BaseModel):
    owner: str


class AccountTokenIn(BaseModel):
    owner: str


class SpendPolicyIn(BaseModel):
    owner: str
    # Agent spend ceiling per donation, in cents. None clears the limit.
    spend_limit_cents: int | None = Field(default=None, ge=0)


class DonationReceiptIn(BaseModel):
    receipt_status: str = "manual_receipt"
    receipt_source: str | None = None
    receipt_ref: str | None = None
    receipt_url: str | None = None
    receipt_artifact_path: str | None = None
    confirmation_notes: str | None = None


class DonationCheckoutIn(BaseModel):
    # Drive the charity's real donate page with the provisioned card. `confirm`
    # only moves real money when the server is in live Link mode (the helper
    # gates the irreversible submit to mode==live AND confirm).
    confirm: bool = False


def default_checkout_runner(pact: Pact, settings: Settings, *, confirm: bool) -> dict:
    """Run the charity-checkout helper as a separate process so the card PAN never
    enters this process. Returns the helper's PAN-free JSON result."""
    import json as _json
    import os
    import subprocess
    import sys

    def checkout_helper_command() -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--pact-charity-checkout"]
        return [sys.executable, "-m", "pact.charity_checkout"]

    charity = get_charity(pact.charity_id)
    url = charity["donation_url"] if charity else pact.charity_url
    shot_dir = os.path.join(settings.artifacts_dir, "checkout")
    os.makedirs(shot_dir, exist_ok=True)
    screenshot = os.path.join(shot_dir, f"checkout_{pact.id}.png")
    args = [
        *checkout_helper_command(),
        "--card-file", pact.card_artifact_path or "",
        "--donation-url", url,
        "--amount-cents", str(pact.stake_amount_cents),
        "--mode", settings.link_mode,
        "--donor-email", pact.owner or "",
        "--screenshot", screenshot,
    ]
    if pact.signer_name:
        args += ["--donor-first", pact.signer_name]
    if confirm and settings.link_mode == "live":
        args.append("--confirm")
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=180)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "submitted": False, "error": str(exc)}
    out = (proc.stdout or "").strip()
    if not out:
        return {"status": "error", "submitted": False, "error": (proc.stderr or "no output")[-500:]}
    try:
        return _json.loads(out.splitlines()[-1])
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "submitted": False, "error": f"unparseable checkout result: {exc}"}


def create_app(
    repo: Repository,
    provider: ReasoningProvider,
    payment: PaymentProvider,
    tokens: TokenStore,
    clock: Clock,
    settings: Settings,
    checkout_runner=None,
) -> FastAPI:
    # Injectable so tests can drive the donation-checkout endpoint without a real
    # browser; production uses the subprocess-isolated Playwright helper.
    checkout_runner = checkout_runner or default_checkout_runner
    app = FastAPI()
    app.state.repo = repo
    raw_payment = payment
    payment = RecordingPaymentProvider(payment, repo, clock, settings)

    @app.get("/api/health", include_in_schema=False)
    def health():
        return {"status": "ok"}

    @app.get("/api/runtime")
    def runtime():
        return {
            "payment_mode": settings.payment_mode,
            "link_mode": settings.link_mode,
            "reasoning_mode": settings.reasoning_mode,
            "auth_mode": settings.auth_mode,
            "live_money_enabled": (
                settings.payment_mode == "link_cli" and settings.link_mode == "live"
            ),
        }

    @app.get("/api/connectors/health")
    def connectors_health(owner: str):
        return build_connector_health(repo, owner, clock, settings)

    def _live_money_enabled() -> bool:
        # Gates the real link-cli subprocess flow (shell on initiate, human-gated
        # approval, automated paths park). "live" moves real money; "live_test" runs
        # the identical flow against Link test credentials (--test) so it can be
        # exercised end-to-end safely.
        return settings.payment_mode == "link_cli" and settings.link_mode in ("live", "live_test")

    def _link_runner():
        return getattr(raw_payment, "runner", None)

    def _sync_live_payment_method(acct) -> None:
        if acct.payment_method_id and hasattr(raw_payment, "payment_method_id"):
            setattr(raw_payment, "payment_method_id", acct.payment_method_id)

    def _link_payload(acct) -> dict:
        ready = bool(acct.connected and (not _live_money_enabled() or acct.payment_method_id))
        return {
            "owner": acct.owner,
            "connected": acct.connected,
            "funding_ref": acct.funding_ref,
            "ready": ready,
            "payment_method_id": acct.payment_method_id,
            "payment_method_label": acct.payment_method_label,
            "payment_method_last4": acct.payment_method_last4,
            "auth_status": acct.auth_status,
            "checked_at": acct.checked_at.isoformat() if acct.checked_at else None,
            "error": acct.error,
        }

    def _refresh_live_link(owner: str, *, interactive: bool):
        acct = repo.get_link_account(owner) or new_account(owner)
        if not _live_money_enabled():
            acct = connect_account(acct, clock)
            repo.save_link_account(acct)
            return acct
        acct = refresh_live_account(
            acct,
            clock,
            runner=_link_runner(),
            preferred_payment_method_id=settings.link_payment_method_id,
            allow_login=interactive,
            allow_add_method=interactive,
        )
        repo.save_link_account(acct)
        _sync_live_payment_method(acct)
        return acct

    def _require_live_link_ready(owner: str):
        acct = repo.get_link_account(owner) or new_account(owner)
        if _live_money_enabled():
            if not acct.connected or not acct.payment_method_id:
                acct = _refresh_live_link(owner, interactive=False)
            if not acct.connected or not acct.payment_method_id:
                raise HTTPException(
                    status_code=409,
                    detail=f"Link live mode is not ready: {acct.error or 'payment method missing'}",
                )
            _sync_live_payment_method(acct)
            return acct
        if not acct.connected:
            acct = connect_account(acct, clock)
            repo.save_link_account(acct)
        return acct

    @app.get("/api/preflight")
    def preflight(owner: str, charity_id: str | None = None, amount_cents: int | None = None):
        live = _live_money_enabled()
        checks: list[dict] = []

        def add(key: str, ok: bool, detail: str, *, live_blocker: bool = True) -> None:
            checks.append(
                {
                    "key": key,
                    "ok": ok,
                    "detail": detail,
                    "live_blocker": live_blocker,
                }
            )

        session = repo.get_agent_session(owner)
        session_ok = bool(
            session
            and session.revoked_at is None
            and (session.expires_at is None or session.expires_at > clock.now())
        )
        add(
            "agent_token",
            session_ok or not live,
            "agent token ready" if session_ok else "no active agent token for owner",
        )

        if live:
            acct = _refresh_live_link(owner, interactive=False)
            link_ok = bool(acct.connected and acct.payment_method_id)
            add(
                "link_payment_method",
                link_ok,
                "Link payment method ready" if link_ok else (acct.error or "Link payment method missing"),
            )
        else:
            add("link_payment_method", True, "not required outside live money mode")

        if charity_id:
            charity = get_charity(charity_id)
            charity_ok = bool(
                charity and is_allowed_url(charity_id, str(charity.get("donation_url", "")))
            )
            add(
                "charity_allowlist",
                charity_ok,
                "charity donation URL is allowlisted"
                if charity_ok
                else "charity is missing or donation URL is not allowlisted",
            )
        else:
            add("charity_allowlist", not live, "no charity selected", live_blocker=live)

        if amount_cents is not None:
            amount_ok = settings.min_stake_cents <= amount_cents <= settings.max_stake_cents
            add(
                "amount_cap",
                amount_ok,
                (
                    f"amount within {settings.min_stake_cents}-{settings.max_stake_cents} cents"
                    if amount_ok
                    else f"amount must be between {settings.min_stake_cents} and {settings.max_stake_cents} cents"
                ),
            )
        else:
            add("amount_cap", not live, "no amount supplied", live_blocker=live)

        clock_ok = settings.clock_mode != "demo"
        add(
            "clock_mode",
            clock_ok or not live,
            "real clock mode" if clock_ok else "demo clock mode cannot run live money",
        )

        issues = [c for c in checks if live and c["live_blocker"] and not c["ok"]]
        return {
            "ready": len(issues) == 0,
            "live_money_enabled": live,
            "owner": owner,
            "checks": checks,
            "issues": issues,
        }

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=False,
        )

    def _require(pact_id: str):
        pact = repo.get_pact(pact_id)
        if pact is None:
            raise HTTPException(status_code=404, detail="pact not found")
        return pact

    def _spend_gate_for(owner: str):
        """The spend gate for an owner, built from their stored policy (agent
        spend limit + approved charities). Every agent-initiated donation passes
        through this deterministic check before money can move."""
        return build_spend_guard(repo.get_profile(owner))

    def _require_agent_session(
        authorization: str | None,
        *,
        required_scope: str | None = None,
    ) -> AgentSession | None:
        if settings.auth_mode == "local_dev":
            return None
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="agent token required")
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise HTTPException(status_code=401, detail="agent token required")
        session = repo.session_for_token_hash(hash_token(token))
        if session is None:
            raise HTTPException(status_code=401, detail="invalid agent token")
        if session.expires_at is not None and session.expires_at < clock.now():
            raise HTTPException(status_code=401, detail="invalid agent token")
        if required_scope is not None and required_scope not in session.scopes:
            raise HTTPException(status_code=403, detail=f"missing scope: {required_scope}")
        session.last_used_at = clock.now()
        repo.save_agent_session(session)
        return session

    def _task_visible_to_session(task, session: AgentSession | None) -> bool:
        if session is None:
            return True
        if task.pact_id is None:
            return False
        pact = repo.get_pact(task.pact_id)
        return bool(pact and pact.owner == session.owner)

    def _message_visible_to_session(msg, session: AgentSession | None) -> bool:
        if session is None:
            return True
        pact = repo.get_pact(msg.pact_id)
        return bool(pact and pact.owner == session.owner)

    def _record_terminal(pact: Pact) -> None:
        """After a terminal settle/dispute, fold the outcome into the owner profile."""
        if pact.status not in _TERMINAL_STATUSES or not pact.owner:
            return
        profile = repo.get_profile(pact.owner) or Profile(owner=pact.owner)
        profile = record_outcome(profile, pact, clock)
        repo.save_profile(profile)

    def _save_terminal_verdict(pact: Pact) -> None:
        if pact.status not in _TERMINAL_STATUSES:
            return
        repo.save_verdict(terminal_verdict(pact, repo.list_proofs(pact.id)))

    def _seed_handoff(pact: Pact) -> None:
        """When a pact goes live, the assigned agent greets the owner with an
        opening coaching message — surfaced in both the web thread and the agent
        outbox. Idempotent: skipped if a handoff already exists for this pact."""
        if any(m.trigger == "handoff" for m in repo.list_coaching_messages(pact.id)):
            return
        charity = get_charity(pact.charity_id)
        msg = generate_coach_message(
            pact, repo.list_proofs(pact.id), "handoff", provider, clock,
            charity["name"] if charity else "charity",
        )
        repo.save_coaching_message(msg)

    @app.post("/api/pacts/draft")
    def draft(body: DraftIn):
        try:
            pact = draft_pact(body.prompt, provider, clock, settings)
        except PactRefused as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        repo.save_pact(pact)
        return pact.model_dump(mode="json")

    @app.post("/api/pacts/create")
    def create_structured(body: CreateIn):
        if body.card_art is not None and body.card_art not in ALLOWED_CARD_ART:
            raise HTTPException(status_code=422, detail="invalid card_art")
        try:
            pact = create_pact_structured(
                goal_title=body.goal_title,
                goal_template=body.goal_template,
                days_per_week=body.days_per_week,
                weeks=body.weeks,
                stake_amount_cents=body.stake_amount_cents,
                charity_id=body.charity_id,
                agent=body.agent,
                consent_acknowledged=body.consent_acknowledged,
                owner=body.owner or "",
                clock=clock,
                settings=settings,
                description=body.description,
                card_art=body.card_art,
                signer_name=body.signer_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        repo.save_pact(pact)
        _seed_handoff(pact)
        return pact.model_dump(mode="json")

    @app.post("/api/pacts")
    def confirm(body: ConfirmIn):
        pact = _require(body.pact_id)
        cards_dir = os.path.join(settings.artifacts_dir, "cards")
        try:
            pact = confirm_and_start(
                pact,
                body.stake_amount_cents,
                body.charity_id,
                clock,
                settings,
                consent_acknowledged=body.consent_acknowledged,
                payment=raw_payment,
                artifacts_dir=cards_dir,
            )
        except (ValueError, TransitionError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        # Pre-authorize at creation: active (card provisioned) in dry-run/test, or
        # awaiting_stake with stake_approval_url in live until the human approves.
        repo.update_pact(pact)
        _seed_handoff(pact)
        return pact.model_dump(mode="json")

    @app.post("/api/pacts/{pact_id}/stake/confirm")
    def stake_confirm(pact_id: str):
        """Pick up the approved stake card after the human approved the spend in Link.
        Idempotent: returns the pact unchanged if already active or still pending."""
        pact = _require(pact_id)
        cards_dir = os.path.join(settings.artifacts_dir, "cards")
        try:
            pact = confirm_stake(pact, raw_payment, clock, settings, artifacts_dir=cards_dir)
        except (ValueError, TransitionError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        repo.update_pact(pact)
        return pact.model_dump(mode="json")

    @app.post("/api/pacts/{pact_id}/owner")
    def set_owner(pact_id: str, body: OwnerIn):
        pact = _require(pact_id)
        pact.owner = body.owner
        repo.update_pact(pact)
        return pact.model_dump(mode="json")

    @app.post("/api/pacts/{pact_id}/start")
    def start(pact_id: str):
        pact = _require(pact_id)
        if pact.status == PactStatus.active:
            return pact.model_dump(mode="json")
        try:
            pact = transition(pact, PactStatus.active)
        except TransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        repo.update_pact(pact)
        return pact.model_dump(mode="json")

    def _with_progress(pact: Pact) -> dict:
        """Pact JSON augmented with the derived `progress` + `cadence` blocks both surfaces use."""
        d = pact.model_dump(mode="json")
        proofs_list = repo.list_proofs(pact.id)
        now = clock.now()
        d["progress"] = compute_progress(pact, proofs_list, now)
        d["cadence"] = compute_cadence(pact, proofs_list, now)
        return d

    def _save_proof_review(proof: Proof, pact: Pact) -> None:
        input_artifacts = {}
        capabilities: list[str] = []
        if proof.artifact_path is not None:
            input_artifacts["artifact_path"] = proof.artifact_path
            capabilities.append("vision")
        if proof.phash is not None:
            input_artifacts["phash"] = proof.phash
        review = ProofReview(
            id=new_pact_id(proof.id + ":review").replace("pact_", "review_"),
            proof_id=proof.id,
            pact_id=proof.pact_id,
            reviewer=pact.agent or "pact-agent",
            capabilities=capabilities,
            input_artifacts=input_artifacts,
            status=proof.status,
            reason=proof.judge_reason,
            checklist=proof.judge_checklist,
            created_at=proof.received_at,
        )
        repo.save_proof_review(review)

    @app.get("/api/pacts/{pact_id}")
    def get_pact(pact_id: str):
        return _with_progress(_require(pact_id))

    @app.get("/api/pacts")
    def list_pacts(owner: str | None = None):
        return [_with_progress(p) for p in repo.list_pacts(owner)]

    @app.post("/api/pacts/{pact_id}/proof-token")
    def proof_token(pact_id: str):
        _require(pact_id)
        token = tokens.issue(pact_id, clock)
        expires_at = tokens.expires_at(token)
        return {
            "token": token,
            "expires_at": expires_at.isoformat() if expires_at else None,
        }

    @app.post("/api/pacts/{pact_id}/proofs")
    def proofs(pact_id: str, body: ProofIn):
        pact = _require(pact_id)
        # Load prior proof phashes from the repo for dedup detection.
        prior_proofs = repo.list_proofs(pact_id)
        prior_phashes = [p.phash for p in prior_proofs if p.phash is not None]
        try:
            proof = submit_proof(
                pact,
                body.modality,
                body.token,
                body.content_ok,
                body.image_path,
                tokens,
                provider,
                clock,
                prior_phashes=prior_phashes,
            )
        except (ValueError, TransitionError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        repo.save_proof(proof)
        _save_proof_review(proof, pact)
        repo.update_pact(pact)
        return proof.model_dump(mode="json")

    @app.get("/api/pacts/{pact_id}/proofs")
    def list_proofs_endpoint(pact_id: str):
        # Server-truth proof list for the UI: 404 if the pact is unknown, else the
        # pact's proofs ordered by received_at (the repo returns them unordered).
        _require(pact_id)
        proofs_list = sorted(
            repo.list_proofs(pact_id), key=lambda p: p.received_at
        )
        return [p.model_dump(mode="json") for p in proofs_list]

    @app.post("/api/pacts/{pact_id}/proofs/image")
    async def proofs_image(
        pact_id: str,
        token: str = Form(...),
        image: UploadFile = File(...),
    ):
        pact = _require(pact_id)

        raw = await image.read()
        try:
            clean = strip_exif(raw)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"invalid image: {exc}")

        # Generate the proof id up front so the artifact filename is stable and
        # matches the Proof we persist. Mirrors submit_proof's id derivation.
        proof_id = new_pact_id(pact.id + token + clock.now().isoformat()).replace(
            "pact_", "proof_"
        )
        image_path, thumb_path = save_proof_image(
            settings.artifacts_dir, pact.id, proof_id, clean
        )
        artifact_meta = {
            "thumbnail_path": thumb_path,
            "mime_type": image.content_type,
            "original_filename": image.filename,
            "size_bytes": len(clean),
        }

        # Dedup is done inside submit_proof via phash_hex(image_path) on the
        # stored file. Every upload follows the same deterministic strip-and-save
        # path, so re-uploading the same photo always collides on the stored hash.
        prior_proofs = repo.list_proofs(pact_id)
        prior_phashes = [p.phash for p in prior_proofs if p.phash is not None]

        try:
            proof = submit_proof(
                pact,
                Modality.photo,
                token,
                False,
                image_path,
                tokens,
                provider,
                clock,
                prior_phashes=prior_phashes,
                artifact_meta=artifact_meta,
            )
        except (ValueError, TransitionError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        repo.save_proof(proof)
        _save_proof_review(proof, pact)
        repo.update_pact(pact)
        return proof.model_dump(mode="json")

    @app.post("/api/pacts/{pact_id}/freeze")
    def freeze(pact_id: str):
        pact = _require(pact_id)
        try:
            pact = spend_freeze(pact, clock)
        except (ValueError, TransitionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        repo.update_pact(pact)
        return pact.model_dump(mode="json")

    @app.post("/api/pacts/{pact_id}/cancel")
    def cancel_pact(pact_id: str):
        pact = _require(pact_id)
        try:
            pact = cancel(pact, clock, settings)
        except (ValueError, TransitionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        # A post-cooling-off forfeit parks in donation_pending; execute the
        # deferred donation here (idempotent, charge-once) so the stake actually
        # moves. An in-cooling-off cancel (canceled_release) is a no-op below.
        if pact.status == PactStatus.donation_pending and not _live_money_enabled():
            pact = execute_forfeit_donation(pact, clock, payment)
        repo.update_pact(pact)
        _record_terminal(pact)
        return pact.model_dump(mode="json")

    @app.post("/api/pacts/{pact_id}/settle")
    def settle_pact(pact_id: str):
        pact = _require(pact_id)
        proofs_list = repo.list_proofs(pact_id)
        if pact.status in (PactStatus.failed, PactStatus.donation_pending):
            # Already failed (or deferred for Link): try to close the dispute window.
            # The donation fires only if the owner has connected a funding source.
            pact, verdict = close_dispute_window(
                pact, proofs_list, clock, payment, settings,
                link_connected=(
                    False if _live_money_enabled() else is_owner_connected(repo, pact.owner)
                ),
                spend_gate=_spend_gate_for(pact.owner),
            )
        else:
            pact, verdict = settle(pact, proofs_list, clock, payment, settings)
        repo.update_pact(pact)
        repo.save_verdict(verdict)
        _record_terminal(pact)
        return verdict.model_dump(mode="json")

    @app.post("/api/pacts/{pact_id}/dispute")
    def dispute(pact_id: str):
        pact = _require(pact_id)
        proofs_list = repo.list_proofs(pact_id)
        try:
            pact, verdict = submit_dispute(pact, proofs_list, clock, payment)
        except (ValueError, TransitionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        repo.update_pact(pact)
        repo.save_verdict(verdict)
        _record_terminal(pact)
        return verdict.model_dump(mode="json")

    @app.post("/api/pacts/{pact_id}/decline")
    def decline(pact_id: str):
        """Owner explicitly declines a pending donation (the nag-until-resolved
        exit). The miss was already recorded at finalization; this resolves the
        open donation so the agent stops nagging."""
        pact = _require(pact_id)
        try:
            pact = decline_donation(pact, clock)
        except TransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        repo.update_pact(pact)
        _record_terminal(pact)
        return pact.model_dump(mode="json")

    # ── Two-phase Link donation (confirm → approve-in-app → monitor → donated) ──
    def _latest_payment_attempt(pact_id: str):
        attempts = repo.list_payment_attempts(pact_id)
        return attempts[-1] if attempts else None

    def _live_attempt_state(status: str | None) -> str | None:
        if payment_status_is_approved(status):
            return "approved"
        if payment_status_is_denied(status):
            return "denied"
        if payment_status_is_expired(status):
            return "expired"
        return None

    def _mark_live_approved(pact: Pact) -> Pact:
        pact.stake_state = StakeState.executed
        pact = transition(pact, PactStatus.donated)
        pact.verdict_at = clock.now()
        repo.update_pact(pact)
        _save_terminal_verdict(pact)
        _record_terminal(pact)
        return pact

    def _mark_live_failed(pact: Pact) -> Pact:
        pact.stake_state = StakeState.error
        pact = transition(pact, PactStatus.donation_failed)
        pact.verdict_at = clock.now()
        repo.update_pact(pact)
        _save_terminal_verdict(pact)
        _record_terminal(pact)
        return pact

    def _poll_live_donation(pact: Pact):
        if not (_live_money_enabled() and pact.status == PactStatus.donation_pending):
            return None
        if not pact.spend_request_id:
            return None
        status = payment.get_donation_status(pact)
        if payment_status_is_approved(status.status):
            _mark_live_approved(pact)
        elif payment_status_is_denied(status.status) or payment_status_is_expired(status.status):
            _mark_live_failed(pact)
        return status

    def _donation_state(pact: Pact) -> dict:
        """Derived donation state for the UI's approve-and-monitor flow.

        state ∈ {idle, awaiting_approval, approved, denied, expired, donated,
        declined, error}.
        - donation_pending + stake_state committed  → idle (owed, not initiated)
        - donation_pending + stake_state executing  → awaiting_approval (spend
          request opened; waiting for the human Link approval)
        - donated                                   → donated (captured, once)
        - donation_declined                         → declined
        """
        if pact.status == PactStatus.donated:
            state = "donated"
        elif pact.status == PactStatus.donation_declined:
            state = "declined"
        else:
            latest = _latest_payment_attempt(pact.id)
            attempt_state = _live_attempt_state(latest.status if latest else None)
            if pact.status == PactStatus.donation_failed and attempt_state in ("denied", "expired"):
                state = attempt_state
            elif pact.status == PactStatus.donation_failed:
            # Provider error during capture (see execute_forfeit_donation): money
            # did NOT move and the pact is terminal — surfaced so the UI can stop
            # waiting instead of spinning on a charge that will never land.
                state = "error"
            elif (
                pact.status == PactStatus.donation_pending
                and pact.stake_state == StakeState.error
                and not pact.spend_request_id
            ):
                # Charge outcome unknown (ambiguous create failure): parked for a
                # human to reconcile; the UI must not auto-retry or claim success.
                state = "reconcile"
            elif pact.status == PactStatus.donation_pending:
                state = attempt_state or (
                    "awaiting_approval"
                    if pact.stake_state == StakeState.executing
                    else "idle"
                )
            else:
                state = "idle"
        latest = _latest_payment_attempt(pact.id)
        return {
            "state": state,
            "status": pact.status.value,
            "stake_state": pact.stake_state.value,
            "spend_request_id": pact.spend_request_id,
            "approval_status": latest.approval_status if latest else None,
            "payment_status": latest.status if latest else None,
        }

    @app.post("/api/pacts/{pact_id}/donation/initiate")
    def donation_initiate(pact_id: str):
        """Open the Link spend-request and move to 'awaiting approval'. No money
        moves here — the human approves in their Link app, then /approve captures.
        Ensures a (test-safe) funding source is registered so capture can proceed."""
        pact = _require(pact_id)
        if pact.status != PactStatus.donation_pending:
            raise HTTPException(
                status_code=409,
                detail=f"donation not pending (status {pact.status.value})",
            )
        _require_live_link_ready(pact.owner)
        # A pact parked for manual reconciliation (an earlier charge had an unknown
        # outcome) must never auto-fire again — link-cli has no idempotency key, so a
        # retry could double-charge. Surface it instead of opening a second request.
        if (
            _live_money_enabled()
            and pact.spend_request_id is None
            and pact.stake_state == StakeState.error
        ):
            raise HTTPException(
                status_code=409,
                detail="donation parked for manual reconciliation (prior charge outcome unknown)",
            )
        # Only open the approval if it hasn't already fired/opened.
        if _live_money_enabled() and pact.spend_request_id is None:
            # Spend gate: clear the owner's policy before opening any live Link
            # spend request. A denial is a clean terminal decline (no charge)
            # surfaced to the UI with the policy reason.
            gate_decision = _spend_gate_for(pact.owner).check(
                SpendRequest(
                    owner=pact.owner,
                    amount_cents=pact.stake_amount_cents,
                    charity_id=pact.charity_id,
                    verified_failure=True,
                )
            )
            if not gate_decision.allowed:
                pact = decline_donation(pact, clock)
                repo.update_pact(pact)
                _record_terminal(pact)
                raise HTTPException(
                    status_code=403,
                    detail=f"Spend blocked by policy: {gate_decision.reason}",
                )
            try:
                result = payment.create_donation(pact, f"{pact.id}:donation")
            except LinkChargeAmbiguous as exc:
                # The request was sent to link-cli but its outcome is unknown. Do NOT
                # mark terminal-failed (money may have moved) and do NOT retry — park
                # for manual reconciliation: stay donation_pending, flag the stake.
                pact.stake_state = StakeState.error
                repo.update_pact(pact)
                raise HTTPException(
                    status_code=502,
                    detail=f"Link spend request status unknown; manual reconcile required: {exc}",
                ) from exc
            except Exception as exc:
                # The request never fired (pre-flight/config error) — no money moved,
                # so leave the pact donation_pending and retryable once the cause is
                # fixed rather than killing collection with a terminal failure.
                raise HTTPException(
                    status_code=502,
                    detail=f"could not create Link spend request: {exc}",
                ) from exc
            pact.spend_request_id = result.provider_ref
            pact.stake_state = StakeState.executing
            if payment_status_is_approved(result.status):
                pact = _mark_live_approved(pact)
            elif payment_status_is_denied(result.status) or payment_status_is_expired(result.status):
                pact = _mark_live_failed(pact)
            else:
                repo.update_pact(pact)
        elif pact.spend_request_id is None and pact.stake_state != StakeState.executed:
            pact.stake_state = StakeState.executing
            repo.update_pact(pact)
        return _donation_state(pact)

    @app.post("/api/pacts/{pact_id}/donation/approve")
    def donation_approve(pact_id: str):
        """The Link approval arrived (real: agent detected it; demo: simulated) —
        capture the donation exactly once. Idempotent on spend_request_id."""
        pact = _require(pact_id)
        if pact.status == PactStatus.donated:
            return _donation_state(pact)
        if pact.status != PactStatus.donation_pending:
            raise HTTPException(
                status_code=409,
                detail=f"donation not pending (status {pact.status.value})",
            )
        if _live_money_enabled():
            if pact.spend_request_id is None:
                raise HTTPException(status_code=409, detail="Link spend request not opened")
            status = _poll_live_donation(pact)
            refreshed = _require(pact_id)
            if refreshed.status == PactStatus.donated:
                return _donation_state(refreshed)
            state = _live_attempt_state(status.status if status else None)
            if state in ("denied", "expired"):
                return _donation_state(_require(pact_id))
            raise HTTPException(
                status_code=409,
                detail=f"Link approval not complete ({status.status if status else 'unknown'})",
            )
        # Reuse the single, idempotent capture path (charge-once on spend_request_id).
        pact = execute_forfeit_donation(pact, clock, payment)
        repo.update_pact(pact)
        _save_terminal_verdict(pact)
        _record_terminal(pact)
        return _donation_state(pact)

    @app.get("/api/pacts/{pact_id}/donation/status")
    def donation_status(pact_id: str):
        """Poll the donation state while the UI waits for the Link approval."""
        pact = _require(pact_id)
        _poll_live_donation(pact)
        return _donation_state(_require(pact_id))

    @app.post("/api/pacts/{pact_id}/donation/card")
    def donation_card(pact_id: str):
        """Provision the approved virtual card to a server-side file so the agent
        can complete the charity's Stripe Checkout (Tier 2). Returns only
        non-secret card metadata — the PAN stays in the file on disk, never in
        the response or the agent's context."""
        import os

        pact = _require(pact_id)
        if not pact.spend_request_id:
            raise HTTPException(
                status_code=409, detail="no spend request to provision a card for"
            )
        # A card carries real charge authority. In live mode the spend request is
        # opened at initiate (donation_pending, pre-approval), so require the human to
        # have actually approved (status donated) before handing out a card.
        if _live_money_enabled():
            if pact.status != PactStatus.donated:
                raise HTTPException(
                    status_code=409,
                    detail=f"card requires an approved (donated) pact (status {pact.status.value})",
                )
        elif pact.status not in (PactStatus.donation_pending, PactStatus.donated):
            raise HTTPException(
                status_code=409,
                detail=f"card requires an approved donation (status {pact.status.value})",
            )
        provisioner = getattr(payment, "retrieve_card", None)
        if provisioner is None:
            raise HTTPException(
                status_code=501, detail="card provisioning not supported by this provider"
            )
        output_dir = os.path.join(settings.artifacts_dir, "cards")
        try:
            cred = provisioner(pact.spend_request_id, output_dir=output_dir)
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"could not provision card: {exc}"
            ) from exc
        pact.card_last4 = cred.last4
        pact.card_artifact_path = cred.card_file
        repo.update_pact(pact)
        return {
            "provisioned": True,
            "last4": cred.last4,
            "brand": cred.brand,
            "exp_month": cred.exp_month,
            "exp_year": cred.exp_year,
            "mode": cred.mode,
        }

    @app.post("/api/pacts/{pact_id}/donation/card-credential")
    def donation_card_credential(
        pact_id: str, authorization: str | None = Header(default=None)
    ):
        """Return the FULL provisioned card (PAN/CVC/expiry) so the OWNER'S OWN AGENT can
        pay on an arbitrary charity's donate page (agent-side crawl).

        This intentionally hands the secret card to the agent — the trade-off accepted for
        any-charity completion. It's bounded: the card is single-use and merchant-locked, so
        the blast radius is one charge to one charity. Gated to the authorized agent/owner
        (no-op in local_dev single-user). Provision the card first via /donation/card.
        """
        pact = _require(pact_id)
        # Safety gate: the chargeable card is released only once the pact is actually
        # payable -- failed + dispute window elapsed (donation_pending) or mid-payment
        # (donated). While the pact is active/awaiting_stake the card stays sealed, so a
        # verified miss + the window are required before the agent can ever charge it.
        if pact.status not in (PactStatus.donation_pending, PactStatus.donated):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"card not releasable in status {pact.status.value}; the donation "
                    "becomes payable only after a verified miss and the dispute window."
                ),
            )
        if not pact.card_artifact_path:
            raise HTTPException(
                status_code=409,
                detail="no provisioned card — call POST /donation/card first",
            )
        session = _require_agent_session(authorization)
        if session is not None and session.owner != pact.owner:
            raise HTTPException(status_code=403, detail="not your pact's card")
        try:
            secret = read_card_secret(pact.card_artifact_path)
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=502, detail=f"could not read provisioned card: {exc}"
            ) from exc
        return secret

    @app.post("/api/pacts/{pact_id}/donation/checkout")
    def donation_checkout(pact_id: str, body: DonationCheckoutIn | None = None):
        """Complete the donation by driving the charity's real donate page with the
        provisioned card (Tier 2). The card must be provisioned first. The helper
        runs in a separate process; the irreversible submit only fires in live Link
        mode with confirm=true. On a real submit, a donation receipt is recorded."""
        pact = _require(pact_id)
        if not pact.card_artifact_path:
            raise HTTPException(
                status_code=409,
                detail="no provisioned card — call POST /donation/card first",
            )
        # Charge-once: a donation already confirmed for this pact must never be driven
        # again — the charity checkout has no idempotency key, so a second submit is a
        # second real charge.
        existing = repo.get_donation_receipt(pact_id)
        if existing and existing.receipt_status == "provider_confirmed":
            raise HTTPException(
                status_code=409, detail="donation already confirmed for this pact"
            )
        confirm = bool(body.confirm) if body else False
        result = checkout_runner(pact, settings, confirm=confirm)
        if result.get("submitted"):
            # Record a donation ONLY on a confirmed outcome. "submitted" means we
            # clicked Give — not that the charge succeeded. A decline is recorded as a
            # failure; an unverifiable ("unknown") outcome records nothing so it can be
            # reconciled rather than masquerading as a completed donation.
            outcome = result.get("outcome")
            confirmed = outcome == "confirmed" or (outcome is None and bool(result.get("reference")))
            if confirmed:
                repo.save_donation_receipt(
                    DonationReceipt(
                        pact_id=pact_id,
                        receipt_status="provider_confirmed",
                        receipt_source="charity_checkout",
                        receipt_ref=result.get("reference"),
                        receipt_artifact_path=result.get("screenshot"),
                        confirmed_at=clock.now(),
                        confirmation_notes=result.get("note"),
                    )
                )
                # Single-use: drop the card ref so a retry can't re-charge it.
                pact.card_artifact_path = None
                repo.update_pact(pact)
            elif outcome == "declined":
                repo.save_donation_receipt(
                    DonationReceipt(
                        pact_id=pact_id,
                        receipt_status="failed_or_reversed",
                        receipt_source="charity_checkout",
                        receipt_artifact_path=result.get("screenshot"),
                        confirmed_at=clock.now(),
                        confirmation_notes=result.get("note") or "charity checkout declined",
                    )
                )
        return result

    @app.post("/api/pacts/{pact_id}/donation/receipt")
    def donation_receipt(pact_id: str, body: DonationReceiptIn):
        pact = _require(pact_id)
        if pact.status != PactStatus.donated:
            raise HTTPException(status_code=409, detail="receipt requires a donated pact")
        if body.receipt_status not in _RECEIPT_STATUSES:
            raise HTTPException(status_code=422, detail="invalid receipt status")
        receipt = DonationReceipt(
            pact_id=pact_id,
            receipt_status=body.receipt_status,
            receipt_source=body.receipt_source,
            receipt_ref=body.receipt_ref,
            receipt_url=body.receipt_url,
            receipt_artifact_path=body.receipt_artifact_path,
            confirmed_at=clock.now(),
            confirmation_notes=body.confirmation_notes,
        )
        repo.save_donation_receipt(receipt)
        # A confirming receipt finalizes the pact to terminal donation_complete.
        pact = finalize_donation(pact, receipt)
        repo.update_pact(pact)
        return receipt.model_dump(mode="json")

    @app.get("/api/pacts/{pact_id}/donation/receipt")
    def get_donation_receipt(pact_id: str):
        _require(pact_id)
        receipt = repo.get_donation_receipt(pact_id)
        if receipt is None:
            raise HTTPException(status_code=404, detail="donation receipt not found")
        return receipt.model_dump(mode="json")

    @app.post("/api/pacts/{pact_id}/donation/confirm")
    def confirm_donation_receipt(pact_id: str):
        pact = _require(pact_id)
        if pact.status != PactStatus.donated:
            raise HTTPException(status_code=409, detail="receipt requires a donated pact")
        existing = repo.get_donation_receipt(pact_id)
        receipt = DonationReceipt(
            pact_id=pact_id,
            receipt_status="provider_confirmed",
            receipt_source=(existing.receipt_source if existing else "provider"),
            receipt_ref=existing.receipt_ref if existing else None,
            receipt_url=existing.receipt_url if existing else None,
            receipt_artifact_path=existing.receipt_artifact_path if existing else None,
            confirmed_at=clock.now(),
            confirmation_notes=(
                existing.confirmation_notes if existing else "Provider confirmation recorded."
            ),
        )
        repo.save_donation_receipt(receipt)
        pact = finalize_donation(pact, receipt)
        repo.update_pact(pact)
        return receipt.model_dump(mode="json")

    @app.post("/api/pacts/{pact_id}/donation/resolve")
    def donation_resolve(pact_id: str):
        """The last mile: after the agent paid the charity with the pre-approved card,
        confirm the charge via Link and resolve the pact to donation_complete. Idempotent;
        if Link cannot confirm yet the pact stays donated and a later resolve retries."""
        pact = _require(pact_id)
        if pact.status not in (PactStatus.donation_pending, PactStatus.donated):
            raise HTTPException(
                status_code=409,
                detail=f"resolve requires a payable pact (donation_pending/donated), got {pact.status.value}",
            )
        pact, receipt = resolve_via_link(pact, payment, clock)
        if receipt is not None:
            repo.save_donation_receipt(receipt)
        repo.update_pact(pact)
        return {
            "status": pact.status.value,
            "confirmed": receipt is not None,
            "receipt": receipt.model_dump(mode="json") if receipt else None,
        }

    @app.get("/api/pacts/{pact_id}/packet")
    def packet(pact_id: str):
        pact = _require(pact_id)
        verdict = repo.get_verdict(pact_id)
        if verdict is None:
            raise HTTPException(status_code=404, detail="no verdict yet")
        proofs_list = repo.list_proofs(pact_id)
        out = build_packet(pact, proofs_list, verdict, receipt=repo.get_donation_receipt(pact_id))
        # Coaching log alongside the verdict (spec §7): merge the thread in here so
        # build_packet keeps its narrow spine signature.
        out["coaching_log"] = [
            m.model_dump(mode="json") for m in repo.list_coaching_messages(pact_id)
        ]
        return out

    @app.get("/api/pacts/{pact_id}/coach")
    def get_coach(pact_id: str):
        _require(pact_id)
        return [
            m.model_dump(mode="json")
            for m in repo.list_coaching_messages(pact_id)
        ]

    @app.post("/api/pacts/{pact_id}/coach")
    async def post_coach(pact_id: str, request: Request):
        pact = _require(pact_id)
        message, attachments = await _read_coach_payload(request, pact_id, settings, clock)
        proofs_list = repo.list_proofs(pact_id)
        inbound, outbound = user_reply(
            pact,
            message,
            proofs_list,
            provider,
            clock,
            attachments=attachments,
        )
        repo.save_coaching_message(inbound)
        repo.save_coaching_message(outbound)
        return {
            "inbound": inbound.model_dump(mode="json"),
            "outbound": outbound.model_dump(mode="json"),
        }

    @app.post("/api/pacts/{pact_id}/renew")
    def renew(pact_id: str):
        old = _require(pact_id)
        # Clone the finished pact's terms into a NEW draft. Fresh id (re-seed off the
        # old id + clock so repeated renews don't collide), status draft, money state
        # reset; the deadline is carried but left for confirm to refresh.
        new_id = new_pact_id(old.id + clock.now().isoformat())
        fresh = old.model_copy(
            update={
                "id": new_id,
                "status": PactStatus.draft,
                "stake_state": StakeState.none,
                "spend_request_id": None,
                "freezes_used": 0,
                "created_at": clock.now(),
                "started_at": None,
                "verdict_at": None,
                # Drop the finished pact's (now-past) dispute horizon; settle() only
                # opens a fresh window when this is None, so a carried-over value
                # would make the renewed pact's failure skip the dispute grace.
                "dispute_window_closes_at": None,
            }
        )
        repo.save_pact(fresh)
        return fresh.model_dump(mode="json")

    @app.get("/api/charities")
    def charities():
        # Surface the curated charity catalogue (id, name, donation_url, category,
        # default_amounts, ...) so the Confirm screen can render the picker.
        return CHARITIES

    @app.get("/api/profile")
    def profile(owner: str):
        prof = repo.get_profile(owner)
        if prof is None:
            # Create-on-read: a default empty profile so the Home screen always renders.
            prof = Profile(owner=owner)
            repo.save_profile(prof)
        return prof.model_dump(mode="json")

    @app.get("/api/policy")
    def get_spend_policy(owner: str):
        """The owner's agent spend authorisation + the active enforcement rail."""
        prof = repo.get_profile(owner) or Profile(owner=owner)
        return {
            "owner": owner,
            "spend_limit_cents": prof.spend_limit_cents,
            "charity_allowlist": all_charity_ids(),
            "rail": build_spend_guard(prof).active_rail,
        }

    @app.post("/api/policy")
    def set_spend_policy(body: SpendPolicyIn, authorization: str | None = Header(default=None)):
        """Set the agent's per-donation spend ceiling ('agent may spend up to $X')."""
        # The spend limit is the authorisation that bounds agent spending, so when auth
        # is enabled a token may only set its OWN owner's policy (no-op in local_dev).
        session = _require_agent_session(authorization)
        if session is not None and session.owner != body.owner:
            raise HTTPException(
                status_code=403, detail="cannot set another owner's spend policy"
            )
        prof = repo.get_profile(body.owner) or Profile(owner=body.owner)
        prof.spend_limit_cents = body.spend_limit_cents
        repo.save_profile(prof)
        return {
            "owner": body.owner,
            "spend_limit_cents": prof.spend_limit_cents,
            "charity_allowlist": all_charity_ids(),
            "rail": build_spend_guard(prof).active_rail,
        }

    @app.get("/api/link/status")
    def link_status(owner: str):
        acct = repo.get_link_account(owner) or new_account(owner)
        return _link_payload(acct)

    @app.get("/api/link/preflight")
    def link_preflight(owner: str):
        acct = repo.get_link_account(owner) or new_account(owner)
        if _live_money_enabled():
            acct = _refresh_live_link(owner, interactive=False)
        return _link_payload(acct)

    @app.post("/api/link/connect")
    def link_connect(body: LinkConnectIn):
        # Test/dry-run registers a deterministic TEST funding source. Live mode
        # shells through link-cli readiness only behind explicit live env gates.
        acct = _refresh_live_link(body.owner, interactive=True)
        return _link_payload(acct)

    @app.post("/api/account/agent-token")
    def mint_agent_token(body: AccountTokenIn):
        # Connect-your-agent seam: mint the token the user pastes into their agent
        # so it claims this account's pacts. The raw token is returned once; only
        # its hash is persisted.
        link, raw_token = link_for(body.owner, clock)
        repo.save_account_link(link)
        return {
            "owner": link.owner,
            "token": raw_token,
            "token_prefix": link.token_prefix,
            "expires_at": link.expires_at.isoformat() if link.expires_at else None,
        }

    @app.get("/api/account/resolve")
    def resolve_agent_token(token: str):
        token_hash = hash_token(token)
        session = repo.session_for_token_hash(token_hash)
        if session is None:
            raise HTTPException(status_code=404, detail="unknown token")
        if session.expires_at is not None and session.expires_at < clock.now():
            raise HTTPException(status_code=404, detail="unknown token")
        session.last_used_at = clock.now()
        repo.save_agent_session(session)
        return {"owner": session.owner, "token_prefix": session.token_prefix}

    @app.post("/api/account/revoke-token")
    def revoke_agent_token(body: AccountTokenIn):
        session = repo.get_agent_session(body.owner)
        if session is None:
            raise HTTPException(status_code=404, detail="unknown owner")
        session.revoked_at = clock.now()
        repo.save_agent_session(session)
        # Keep the legacy account link row coherent for callers that still read it.
        link = repo.get_account_link(body.owner)
        if link is not None:
            link.revoked_at = session.revoked_at
            repo.save_account_link(link)
        return {"owner": body.owner, "revoked": True, "token_prefix": session.token_prefix}

    @app.post("/demo/seed")
    def demo_seed_endpoint():
        ids = demo_seed(repo, clock, settings)
        # Layer the showcase pacts (every Detail state + a fuller carousel/ledger)
        # for the live demo. Side-effect only — the response stays {win,fail,live}.
        demo_seed_states(repo, clock, settings)
        return ids

    @app.post("/demo/advance-day")
    def demo_advance_day_endpoint():
        if not isinstance(clock, FixedClock):
            raise HTTPException(
                status_code=409,
                detail="advance-day requires demo clock mode (FixedClock)",
            )
        return demo_advance_day(repo, clock, payment, settings)

    @app.post("/demo/reset")
    def demo_reset_endpoint():
        if not isinstance(clock, FixedClock):
            raise HTTPException(
                status_code=409,
                detail="reset requires demo clock mode (FixedClock)",
            )
        ids = demo_reset(repo, clock, settings)
        demo_seed_states(repo, clock, settings)
        return ids

    @app.post("/api/pacts/{pact_id}/reasoning-tasks")
    def enqueue_reasoning_task(pact_id: str, body: EnqueueTaskIn):
        _require(pact_id)
        task = broker.enqueue(
            repo,
            body.type,
            pact_id,
            body.input,
            clock,
            required_capability=body.required_capability,
        )
        return task.model_dump(mode="json")

    @app.get("/api/reasoning-tasks")
    def list_reasoning_tasks(
        capability: str | None = None,
        status: str | None = None,
        authorization: str | None = Header(default=None),
    ):
        session = _require_agent_session(authorization, required_scope="claim_tasks")
        # A worker polling for work is the liveness beat the reasoning provider
        # uses to decide whether to wait for the agent brain.
        repo.mark_worker_seen(clock.now())
        # Only "pending" is exposed; the broker storage of pending tasks is the
        # work queue. `status` is accepted for forward-compat / clarity but the
        # broker always returns pending tasks here.
        tasks = broker.pending_for(repo, capability)
        tasks = [t for t in tasks if _task_visible_to_session(t, session)]
        return [t.model_dump(mode="json") for t in tasks]

    @app.post("/api/reasoning-tasks/{tid}/claim")
    def claim_reasoning_task(
        tid: str,
        body: ClaimTaskIn,
        authorization: str | None = Header(default=None),
    ):
        session = _require_agent_session(authorization, required_scope="claim_tasks")
        existing = repo.get_task(tid)
        if existing is not None and not _task_visible_to_session(existing, session):
            raise HTTPException(status_code=403, detail="task belongs to another owner")
        try:
            task = broker.claim(repo, tid, body.agent_name, set(body.capabilities))
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return task.model_dump(mode="json")

    @app.post("/api/reasoning-tasks/{tid}/result")
    def post_reasoning_task_result(
        tid: str,
        body: TaskResultIn,
        authorization: str | None = Header(default=None),
    ):
        session = _require_agent_session(authorization, required_scope="post_results")
        existing = repo.get_task(tid)
        if existing is not None and not _task_visible_to_session(existing, session):
            raise HTTPException(status_code=403, detail="task belongs to another owner")
        try:
            task = broker.post_result(repo, tid, body.result)
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return task.model_dump(mode="json")

    @app.post("/api/tick")
    def tick_endpoint():
        """Run one scheduler sweep: reconcile, close dispute windows, nudge."""
        return scheduler_tick(repo, clock, payment, settings)

    @app.get("/api/outbox")
    def outbox(owner: str, authorization: str | None = Header(default=None)):
        """Return the owner's undelivered outbound coaching messages (the relay queue).

        The Hermes agent fetches this, relays each nudge through its own channel,
        then marks each message delivered via POST /api/coach/{msg_id}/delivered.
        """
        session = _require_agent_session(authorization, required_scope="relay_outbox")
        if session is not None and owner != session.owner:
            raise HTTPException(status_code=403, detail="outbox belongs to another owner")
        return [m.model_dump(mode="json") for m in repo.outbox(owner)]

    @app.post("/api/coach/{msg_id}/delivered")
    def mark_delivered(
        msg_id: str,
        authorization: str | None = Header(default=None),
    ):
        """Mark a coaching message as delivered. Returns 404 if the message does not exist."""
        session = _require_agent_session(authorization, required_scope="relay_outbox")
        msg = repo.get_coaching_message(msg_id)
        if msg is None:
            raise HTTPException(status_code=404, detail="coaching message not found")
        if not _message_visible_to_session(msg, session):
            raise HTTPException(status_code=403, detail="message belongs to another owner")
        msg = msg.model_copy(update={"delivered_at": clock.now()})
        repo.save_coaching_message(msg)
        return msg.model_dump(mode="json")

    return app

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from pact import broker
from pact.anticheat import TokenStore
from pact.charities import CHARITIES
from pact.clock import Clock, FixedClock
from pact.coaching import user_reply
from pact.config import Settings
from pact.demo import advance_day as demo_advance_day
from pact.demo import reset as demo_reset
from pact.demo import seed as demo_seed
from pact.lifecycle import (
    PactRefused,
    TransitionError,
    cancel,
    confirm_and_start,
    draft_pact,
    new_pact_id,
    settle,
    spend_freeze,
    submit_dispute,
    submit_proof,
    transition,
)
from pact.models import Modality, Pact, PactStatus, Profile, StakeState, TaskType
from pact.packet import build_packet
from pact.payment import PaymentProvider
from pact.profile import record_outcome
from pact.reasoning import ReasoningProvider
from pact.repository import Repository

_TERMINAL_STATUSES = {
    PactStatus.succeeded,
    PactStatus.failed,
    PactStatus.donated,
    PactStatus.donation_failed,
    PactStatus.donation_declined,
    PactStatus.canceled_forfeit,
}


class DraftIn(BaseModel):
    prompt: str


class ConfirmIn(BaseModel):
    pact_id: str
    stake_amount_cents: int
    charity_id: str


class ProofIn(BaseModel):
    modality: Modality
    token: str
    content_ok: bool = True
    image_path: str | None = None


class OwnerIn(BaseModel):
    owner: str


class CoachIn(BaseModel):
    message: str


class EnqueueTaskIn(BaseModel):
    type: TaskType
    input: dict
    required_capability: str | None = None


class ClaimTaskIn(BaseModel):
    agent_name: str
    capabilities: list[str]


class TaskResultIn(BaseModel):
    result: dict


def create_app(
    repo: Repository,
    provider: ReasoningProvider,
    payment: PaymentProvider,
    tokens: TokenStore,
    clock: Clock,
    settings: Settings,
) -> FastAPI:
    app = FastAPI()

    def _require(pact_id: str):
        pact = repo.get_pact(pact_id)
        if pact is None:
            raise HTTPException(status_code=404, detail="pact not found")
        return pact

    def _record_terminal(pact: Pact) -> None:
        """After a terminal settle/dispute, fold the outcome into the owner profile."""
        if pact.status not in _TERMINAL_STATUSES or not pact.owner:
            return
        profile = repo.get_profile(pact.owner) or Profile(owner=pact.owner)
        profile = record_outcome(profile, pact, clock)
        repo.save_profile(profile)

    @app.post("/api/pacts/draft")
    def draft(body: DraftIn):
        try:
            pact = draft_pact(body.prompt, provider, clock, settings)
        except PactRefused as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        repo.save_pact(pact)
        return pact.model_dump(mode="json")

    @app.post("/api/pacts")
    def confirm(body: ConfirmIn):
        pact = _require(body.pact_id)
        try:
            pact = confirm_and_start(
                pact, body.stake_amount_cents, body.charity_id, clock, settings
            )
        except (ValueError, TransitionError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        # confirm_and_start already activates; persist as-is.
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

    @app.get("/api/pacts/{pact_id}")
    def get_pact(pact_id: str):
        return _require(pact_id).model_dump(mode="json")

    @app.get("/api/pacts")
    def list_pacts(owner: str | None = None):
        return [p.model_dump(mode="json") for p in repo.list_pacts(owner)]

    @app.post("/api/pacts/{pact_id}/proof-token")
    def proof_token(pact_id: str):
        _require(pact_id)
        token = tokens.issue(pact_id, clock)
        return {"token": token}

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
        repo.update_pact(pact)
        _record_terminal(pact)
        return pact.model_dump(mode="json")

    @app.post("/api/pacts/{pact_id}/settle")
    def settle_pact(pact_id: str):
        pact = _require(pact_id)
        proofs_list = repo.list_proofs(pact_id)
        pact, verdict = settle(pact, proofs_list, clock, payment)
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

    @app.get("/api/pacts/{pact_id}/packet")
    def packet(pact_id: str):
        pact = _require(pact_id)
        verdict = repo.get_verdict(pact_id)
        if verdict is None:
            raise HTTPException(status_code=404, detail="no verdict yet")
        proofs_list = repo.list_proofs(pact_id)
        out = build_packet(pact, proofs_list, verdict)
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
    def post_coach(pact_id: str, body: CoachIn):
        pact = _require(pact_id)
        inbound, outbound = user_reply(pact, body.message, provider, clock)
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

    @app.post("/demo/seed")
    def demo_seed_endpoint():
        return demo_seed(repo, clock, settings)

    @app.post("/demo/advance-day")
    def demo_advance_day_endpoint():
        if not isinstance(clock, FixedClock):
            raise HTTPException(
                status_code=409,
                detail="advance-day requires demo clock mode (FixedClock)",
            )
        return demo_advance_day(repo, clock, payment)

    @app.post("/demo/reset")
    def demo_reset_endpoint():
        if not isinstance(clock, FixedClock):
            raise HTTPException(
                status_code=409,
                detail="reset requires demo clock mode (FixedClock)",
            )
        return demo_reset(repo, clock, settings)

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
        capability: str | None = None, status: str | None = None
    ):
        # Only "pending" is exposed; the broker storage of pending tasks is the
        # work queue. `status` is accepted for forward-compat / clarity but the
        # broker always returns pending tasks here.
        tasks = broker.pending_for(repo, capability)
        return [t.model_dump(mode="json") for t in tasks]

    @app.post("/api/reasoning-tasks/{tid}/claim")
    def claim_reasoning_task(tid: str, body: ClaimTaskIn):
        try:
            task = broker.claim(repo, tid, body.agent_name, set(body.capabilities))
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return task.model_dump(mode="json")

    @app.post("/api/reasoning-tasks/{tid}/result")
    def post_reasoning_task_result(tid: str, body: TaskResultIn):
        try:
            task = broker.post_result(repo, tid, body.result)
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return task.model_dump(mode="json")

    return app

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from pact.anticheat import TokenStore, phash_hex
from pact.clock import Clock
from pact.config import Settings
from pact.lifecycle import (
    PactRefused,
    TransitionError,
    cancel,
    confirm_and_start,
    draft_pact,
    settle,
    spend_freeze,
    submit_dispute,
    submit_proof,
    transition,
)
from pact.models import Modality, PactStatus
from pact.packet import build_packet
from pact.payment import PaymentProvider
from pact.reasoning import ReasoningProvider
from pact.repository import Repository


class DraftIn(BaseModel):
    prompt: str


class ConfirmIn(BaseModel):
    pact_id: str
    stake_amount_cents: int
    charity_id: str


class ProofIn(BaseModel):
    modality: Modality
    token: str
    token_in_image: bool = True
    content_ok: bool = True
    image_path: str | None = None


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
                body.token_in_image,
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
        return pact.model_dump(mode="json")

    @app.post("/api/pacts/{pact_id}/settle")
    def settle_pact(pact_id: str):
        pact = _require(pact_id)
        proofs_list = repo.list_proofs(pact_id)
        pact, verdict = settle(pact, proofs_list, clock, payment)
        repo.update_pact(pact)
        repo.save_verdict(verdict)
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
        return verdict.model_dump(mode="json")

    @app.get("/api/pacts/{pact_id}/packet")
    def packet(pact_id: str):
        pact = _require(pact_id)
        verdict = repo.get_verdict(pact_id)
        if verdict is None:
            raise HTTPException(status_code=404, detail="no verdict yet")
        proofs_list = repo.list_proofs(pact_id)
        return build_packet(pact, proofs_list, verdict)

    return app

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock
from pact.coaching import user_reply
from pact.config import Settings
from pact.lifecycle import cancel, execute_forfeit_donation
from pact.models import (
    Modality,
    Pact,
    PactStatus,
    Proof,
    ProofStatus,
    Rubric,
    StakeState,
)
from pact.payment import PaymentResult, TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


# ─── Shared fixtures/helpers ──────────────────────────────────────────────────

class SpyPaymentProvider:
    """Counts create_donation calls; delegates to a real TestLinkProvider."""

    def __init__(self):
        self.calls = 0
        self.last_idempotency_key = None
        self._inner = TestLinkProvider()

    def create_donation(self, pact: Pact, idempotency_key: str) -> PaymentResult:
        self.calls += 1
        self.last_idempotency_key = idempotency_key
        return self._inner.create_donation(pact, idempotency_key)


def _rubric() -> Rubric:
    return Rubric(
        modality=Modality.photo,
        must_show=["clear evidence the committed action was performed"],
        min_distinct_days=5,
        count_target=5,
    )


def _active_pact(clock: FixedClock, *, target: int = 5) -> Pact:
    now = clock.now()
    return Pact(
        id="pact_forfeit1",
        owner="demo@pact.local",
        original_prompt="do the thing 5x or $5 to charity",
        title="Do the thing 5x",
        goal="Complete the thing on 5 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=now + timedelta(days=3),
        target_count=target,
        distinct_days=True,
        recommended_stake_cents=500,
        stake_amount_cents=500,
        charity_id="world_central_kitchen",
        charity_url="https://wck.org/donate",
        rubric=_rubric(),
        status=PactStatus.active,
        stake_state=StakeState.committed,
        created_at=now,
        started_at=now,
    )


def _passed_proof(idx: int, day: str, received: datetime) -> Proof:
    return Proof(
        id=f"proof_{idx}",
        pact_id="pact_forfeit1",
        modality=Modality.photo,
        received_at=received,
        day_bucket=day,
        token_ok=True,
        status=ProofStatus.passed,
    )


# ─── (a) Forfeit cancel: record failure + execute the donation once ───────────

def test_execute_forfeit_donation_moves_stake_once_then_idempotent():
    clock = FixedClock(datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc))
    settings = Settings()  # cooling_off_minutes default 60
    pact = _active_pact(clock)

    clock.advance(minutes=90)  # past the cooling-off window -> real forfeit
    forfeited = cancel(pact, clock, settings)
    assert forfeited.status == PactStatus.donation_pending
    assert forfeited.spend_request_id is None  # cancel does NOT move money

    payment = SpyPaymentProvider()
    donated = execute_forfeit_donation(forfeited, clock, payment)

    assert donated.status == PactStatus.donated
    assert donated.stake_state == StakeState.executed
    assert payment.calls == 1
    assert payment.last_idempotency_key == "pact_forfeit1:donation"
    assert donated.spend_request_id == "test_sr_pact_forfeit1_500"

    # Idempotent: a second call moves no further money and changes nothing.
    again = execute_forfeit_donation(donated, clock, payment)
    assert payment.calls == 1
    assert again.status == PactStatus.donated
    assert again.spend_request_id == donated.spend_request_id


def _build_app(tmp_path, clock):
    db = str(tmp_path / "pact.db")
    repo = Repository.connect(db)
    repo.init_schema()
    provider = TestLLMProvider()
    payment = SpyPaymentProvider()
    tokens = TokenStore(ttl_minutes=10)
    settings = Settings(db_path=db)
    app = create_app(repo, provider, payment, tokens, clock, settings)
    return app, repo, payment


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_api_forfeit_cancel_records_failed_and_executes_donation(tmp_path):
    owner = "demo@pact.local"
    clock = FixedClock(datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc))
    app, repo, payment = _build_app(tmp_path, clock)

    async with _client(app) as client:
        # Draft -> confirm -> owner -> start.
        r = await client.post(
            "/api/pacts/draft",
            json={"prompt": "do a thing 5x this week or $15 to charity"},
        )
        assert r.status_code == 200, r.text
        pact_id = r.json()["id"]

        r = await client.post(
            "/api/pacts",
            json={
                "pact_id": pact_id,
                "stake_amount_cents": 1500,
                "charity_id": "world_central_kitchen",
            },
        )
        assert r.status_code == 200, r.text
        r = await client.post(f"/api/pacts/{pact_id}/owner", json={"owner": owner})
        assert r.status_code == 200, r.text
        r = await client.post(f"/api/pacts/{pact_id}/start")
        assert r.status_code == 200, r.text

        # Advance past cooling-off, then cancel -> forfeit.
        clock.advance(minutes=90)
        r = await client.post(f"/api/pacts/{pact_id}/cancel")
        assert r.status_code == 200, r.text
        body = r.json()
        # Forfeit actually moved the stake: donated, exactly one payment call.
        assert body["status"] == "donated"
        assert body["spend_request_id"] == f"test_sr_{pact_id}_1500"
        assert payment.calls == 1

        # Owner profile records the forfeit as a failure.
        r = await client.get("/api/profile", params={"owner": owner})
        assert r.status_code == 200, r.text
        prof = r.json()
        assert prof["failed"] == 1
        assert prof["kept"] == 0
        assert prof["current_streak"] == 0
        assert pact_id in prof["pact_ids"]
        assert prof["history"][0]["pact_id"] == pact_id
        assert prof["history"][0]["outcome"] == "failed"


# ─── (b) user_reply threads the real valid count ──────────────────────────────

def test_user_reply_reflects_real_valid_count():
    clock = FixedClock(datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc))
    pact = _active_pact(clock, target=5)
    base = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
    # 3 passed proofs on 3 distinct day buckets -> valid count 3.
    proofs = [
        _passed_proof(0, "2026-06-20", base),
        _passed_proof(1, "2026-06-21", base + timedelta(days=1)),
        _passed_proof(2, "2026-06-22", base + timedelta(days=2)),
    ]

    provider = TestLLMProvider()
    inbound, outbound = user_reply(pact, "how am I doing?", proofs, provider, clock)

    assert inbound.direction == "inbound"
    assert inbound.body == "how am I doing?"
    # The coach stub echoes "<valid> of <target> done" — real count, not 0.
    assert "3 of 5 done" in outbound.body
    assert outbound.pact_state_snapshot["valid"] == 3
    assert outbound.pact_state_snapshot["target"] == 5

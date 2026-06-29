import subprocess
from datetime import datetime, timezone

from pact.clock import FixedClock
from pact.link import connect_account, new_account, refresh_live_account


def _clock() -> FixedClock:
    return FixedClock(datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc))


def test_new_account_defaults_disconnected():
    acct = new_account("a@b.com")
    assert acct.owner == "a@b.com"
    assert acct.connected is False
    assert acct.funding_ref is None
    assert acct.connected_at is None


def test_connect_sets_connected_and_funding_ref():
    clock = _clock()
    acct = connect_account(new_account("a@b.com"), clock)
    assert acct.connected is True
    assert acct.funding_ref == "test_funding_a@b.com"
    assert acct.connected_at == clock.now()


def test_connect_is_idempotent():
    clock = _clock()
    once = connect_account(new_account("a@b.com"), clock)
    later = FixedClock(datetime(2026, 7, 1, tzinfo=timezone.utc))
    twice = connect_account(once, later)
    # Re-connecting changes nothing (keeps the original connected_at).
    assert twice.connected_at == clock.now()
    assert twice.funding_ref == "test_funding_a@b.com"


class _FakeRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def run(self, args, timeout):
        self.calls.append((args, timeout))
        if not self.responses:
            raise AssertionError(f"unexpected link-cli call: {args!r}")
        return self.responses.pop(0)


def test_refresh_live_account_stores_usable_payment_method_without_secrets():
    clock = _clock()
    runner = _FakeRunner([
        {"authenticated": True, "status": "authenticated"},
        {
            "payment_methods": [
                {
                    "id": "pm_live_123",
                    "label": "Visa",
                    "last4": "4242",
                    "status": "active",
                    "card": {"last4": "9999", "number": "4111111111111111"},
                }
            ]
        },
    ])

    acct = refresh_live_account(new_account("a@b.com"), clock, runner=runner)

    assert acct.connected is True
    assert acct.funding_ref == "pm_live_123"
    assert acct.payment_method_id == "pm_live_123"
    assert acct.payment_method_label == "Visa"
    assert acct.payment_method_last4 == "4242"
    assert acct.auth_status == "authenticated"
    assert acct.checked_at == clock.now()
    assert "411111" not in acct.model_dump_json()
    assert runner.calls == [
        (["link-cli", "auth", "status", "--format", "json"], 120),
        (["link-cli", "payment-methods", "list", "--format", "json"], 120),
    ]


def test_refresh_live_account_can_login_and_add_payment_method_when_requested():
    clock = _clock()
    runner = _FakeRunner([
        {"authenticated": False, "status": "signed_out"},
        {"ok": True},
        {"authenticated": True, "status": "authenticated"},
        {"payment_methods": []},
        {"ok": True},
        {"payment_methods": [{"id": "pm_added", "brand": "Amex", "last4": "0005"}]},
    ])

    acct = refresh_live_account(
        new_account("a@b.com"),
        clock,
        runner=runner,
        allow_login=True,
        allow_add_method=True,
    )

    assert acct.connected is True
    assert acct.payment_method_id == "pm_added"
    assert runner.calls == [
        (["link-cli", "auth", "status", "--format", "json"], 120),
        (["link-cli", "auth", "login", "--client-name", "Pact"], 120),
        (["link-cli", "auth", "status", "--format", "json"], 120),
        (["link-cli", "payment-methods", "list", "--format", "json"], 120),
        (["link-cli", "payment-methods", "add"], 120),
        (["link-cli", "payment-methods", "list", "--format", "json"], 120),
    ]


def test_refresh_live_account_reports_not_ready_without_auth():
    clock = _clock()
    runner = _FakeRunner([{"authenticated": False, "status": "signed_out"}])

    acct = refresh_live_account(new_account("a@b.com"), clock, runner=runner)

    assert acct.connected is False
    assert acct.auth_status == "signed_out"
    assert acct.error == "Link CLI is not authenticated"
    assert acct.payment_method_id is None


def test_repo_round_trips_link_account(tmp_path):
    from pact.repository import Repository

    repo = Repository.connect(str(tmp_path / "p.db"))
    repo.init_schema()
    assert repo.get_link_account("a@b.com") is None
    repo.save_link_account(connect_account(new_account("a@b.com"), _clock()))
    got = repo.get_link_account("a@b.com")
    assert got is not None and got.connected is True
    assert got.funding_ref == "test_funding_a@b.com"


# ── API + settlement-gate tests ──────────────────────────────────────────────

import httpx  # noqa: E402
import pytest  # noqa: E402

from pact.anticheat import TokenStore  # noqa: E402
from pact.api import create_app  # noqa: E402
from pact.config import Settings  # noqa: E402
from pact.models import (  # noqa: E402
    AgentSession,
    LinkAccount,
    Modality,
    Pact,
    PactStatus,
    Rubric,
    StakeState,
)
from pact.payment import LinkCliProvider, TestLinkProvider  # noqa: E402
from pact.reasoning import TestLLMProvider  # noqa: E402
from pact.repository import Repository  # noqa: E402
from datetime import timedelta  # noqa: E402


class _SpyPayment:
    def __init__(self):
        self.calls = 0
        self._inner = TestLinkProvider()

    def create_donation(self, pact, idempotency_key):
        self.calls += 1
        return self._inner.create_donation(pact, idempotency_key)


def _build(tmp_path, clock, payment=None):
    db = str(tmp_path / "p.db")
    repo = Repository.connect(db)
    repo.init_schema()
    settings = Settings(db_path=db)
    payment = payment or _SpyPayment()
    app = create_app(repo, TestLLMProvider(), payment, TokenStore(), clock, settings)
    return app, repo, payment


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _failing_pact(clock, owner: str) -> Pact:
    now = clock.now()
    return Pact(
        id="pact_gate1",
        owner=owner,
        original_prompt="do the thing 5x or $20 to charity",
        title="Do the thing",
        goal="Complete the thing on 5 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=now + timedelta(days=1),
        target_count=5,
        recommended_stake_cents=2000,
        stake_amount_cents=2000,
        charity_id="against_malaria_foundation",
        charity_url="https://againstmalaria.com/donate",
        rubric=Rubric(modality=Modality.photo, must_show=["x"], min_distinct_days=5, count_target=5),
        status=PactStatus.active,
        stake_state=StakeState.committed,
        created_at=now,
        started_at=now,
    )


@pytest.mark.asyncio
async def test_link_status_then_connect(tmp_path):
    clock = _clock()
    app, _, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        r = await client.get("/api/link/status", params={"owner": "a@b.com"})
        assert r.json()["owner"] == "a@b.com"
        assert r.json()["connected"] is False
        assert r.json()["funding_ref"] is None
        assert r.json()["ready"] is False

        r = await client.post("/api/link/connect", json={"owner": "a@b.com"})
        assert r.status_code == 200, r.text
        assert r.json()["connected"] is True
        assert r.json()["funding_ref"] == "test_funding_a@b.com"
        assert r.json()["ready"] is True

        r = await client.get("/api/link/status", params={"owner": "a@b.com"})
        assert r.json()["connected"] is True


@pytest.mark.asyncio
async def test_settlement_is_gated_on_link_connection(tmp_path):
    owner = "a@b.com"
    clock = _clock()
    app, repo, payment = _build(tmp_path, clock)
    repo.save_pact(_failing_pact(clock, owner))

    async with _client(app) as client:
        # Cross the deadline → settle → failed, dispute window opens, no money.
        clock.advance(days=2)
        r = await client.post("/api/pacts/pact_gate1/settle")
        assert r.json()["status"] == "failed"
        assert payment.calls == 0

        # Cross the dispute window → settle, but Link is NOT connected → deferred.
        clock.advance(days=5)
        await client.post("/api/pacts/pact_gate1/settle")
        assert payment.calls == 0
        p = await client.get("/api/pacts/pact_gate1")
        assert p.json()["status"] == "donation_pending"

        # Connect Link → settle again → the deferred donation fires exactly once.
        await client.post("/api/link/connect", json={"owner": owner})
        await client.post("/api/pacts/pact_gate1/settle")
        assert payment.calls == 1
        p = await client.get("/api/pacts/pact_gate1")
        assert p.json()["status"] == "donated"


@pytest.mark.asyncio
async def test_live_link_preflight_persists_readiness_and_syncs_provider(tmp_path):
    clock = _clock()
    db = str(tmp_path / "p.db")
    repo = Repository.connect(db)
    repo.init_schema()
    runner = _FakeRunner([
        {"authenticated": True, "status": "authenticated"},
        {"payment_methods": [{"id": "pm_live_123", "label": "Visa", "last4": "4242"}]},
    ])
    payment = LinkCliProvider(link_mode="live", runner=runner)
    settings = Settings(db_path=db, payment_mode="link_cli", link_mode="live")
    app = create_app(repo, TestLLMProvider(), payment, TokenStore(), clock, settings)

    async with _client(app) as client:
        r = await client.get("/api/link/preflight", params={"owner": "a@b.com"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ready"] is True
        assert body["payment_method_id"] == "pm_live_123"
        assert body["payment_method_last4"] == "4242"

    acct = repo.get_link_account("a@b.com")
    assert acct is not None
    assert acct.connected is True
    assert acct.payment_method_id == "pm_live_123"
    assert payment.payment_method_id == "pm_live_123"


@pytest.mark.asyncio
async def test_live_preflight_reports_blockers(tmp_path):
    clock = _clock()
    db = str(tmp_path / "p.db")
    repo = Repository.connect(db)
    repo.init_schema()
    runner = _FakeRunner([{"authenticated": False, "status": "signed_out"}])
    payment = LinkCliProvider(link_mode="live", runner=runner)
    settings = Settings(
        db_path=db,
        payment_mode="link_cli",
        link_mode="live",
        clock_mode="demo",
    )
    app = create_app(repo, TestLLMProvider(), payment, TokenStore(), clock, settings)

    async with _client(app) as client:
        r = await client.get(
            "/api/preflight",
            params={
                "owner": "a@b.com",
                "charity_id": "against_malaria_foundation",
                "amount_cents": 2000,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()

    assert body["ready"] is False
    issue_keys = {issue["key"] for issue in body["issues"]}
    assert {"agent_token", "link_payment_method", "clock_mode"}.issubset(issue_keys)


@pytest.mark.asyncio
async def test_live_preflight_ready_with_agent_link_amount_and_allowlisted_charity(tmp_path):
    clock = _clock()
    db = str(tmp_path / "p.db")
    repo = Repository.connect(db)
    repo.init_schema()
    repo.save_agent_session(
        AgentSession(
            owner="a@b.com",
            token_hash="hash",
            token_prefix="pat_ready",
            created_at=clock.now(),
            expires_at=clock.now() + timedelta(days=30),
            scopes=["claim_tasks", "post_results", "relay_outbox"],
        )
    )
    runner = _FakeRunner([
        {"authenticated": True, "status": "authenticated"},
        {"payment_methods": [{"id": "pm_live_123", "last4": "4242"}]},
    ])
    payment = LinkCliProvider(link_mode="live", runner=runner)
    settings = Settings(db_path=db, payment_mode="link_cli", link_mode="live")
    app = create_app(repo, TestLLMProvider(), payment, TokenStore(), clock, settings)

    async with _client(app) as client:
        r = await client.get(
            "/api/preflight",
            params={
                "owner": "a@b.com",
                "charity_id": "against_malaria_foundation",
                "amount_cents": 2000,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()

    assert body["ready"] is True
    assert body["issues"] == []
    assert {check["key"] for check in body["checks"]} == {
        "agent_token",
        "link_payment_method",
        "charity_allowlist",
        "amount_cap",
        "clock_mode",
    }


@pytest.mark.asyncio
async def test_live_donation_initiate_blocks_when_link_is_not_ready(tmp_path):
    owner = "a@b.com"
    clock = _clock()
    db = str(tmp_path / "p.db")
    repo = Repository.connect(db)
    repo.init_schema()
    repo.save_pact(
        _failing_pact(clock, owner).model_copy(
            update={
                "status": PactStatus.donation_pending,
                "stake_state": StakeState.committed,
            }
        )
    )
    runner = _FakeRunner([{"authenticated": False, "status": "signed_out"}])
    payment = LinkCliProvider(link_mode="live", runner=runner)
    settings = Settings(db_path=db, payment_mode="link_cli", link_mode="live")
    app = create_app(repo, TestLLMProvider(), payment, TokenStore(), clock, settings)

    async with _client(app) as client:
        r = await client.post("/api/pacts/pact_gate1/donation/initiate")
        assert r.status_code == 409
        assert "Link live mode is not ready" in r.text

    pact = repo.get_pact("pact_gate1")
    assert pact is not None
    assert pact.status == PactStatus.donation_pending
    assert pact.stake_state == StakeState.committed


@pytest.mark.asyncio
async def test_live_donation_creates_request_then_waits_for_approval(tmp_path):
    owner = "a@b.com"
    clock = _clock()
    db = str(tmp_path / "p.db")
    repo = Repository.connect(db)
    repo.init_schema()
    repo.save_pact(
        _failing_pact(clock, owner).model_copy(
            update={
                "status": PactStatus.donation_pending,
                "stake_state": StakeState.committed,
            }
        )
    )
    repo.save_link_account(
        LinkAccount(
            owner=owner,
            connected=True,
            funding_ref="pm_live_123",
            connected_at=clock.now(),
            payment_method_id="pm_live_123",
            auth_status="authenticated",
            checked_at=clock.now(),
        )
    )
    runner = _FakeRunner([
        {"id": "sr_live_1", "status": "pending_approval"},  # create (--no-request-approval)
        {"id": "sr_live_1", "status": "pending_approval"},  # request-approval (prompt human)
        {"id": "sr_live_1", "status": "pending_approval"},  # approve #1 retrieve -> still waiting
        {"id": "sr_live_1", "status": "approved"},          # approve #2 retrieve -> approved
    ])
    payment = LinkCliProvider(link_mode="live", runner=runner)
    settings = Settings(db_path=db, payment_mode="link_cli", link_mode="live")
    app = create_app(repo, TestLLMProvider(), payment, TokenStore(), clock, settings)

    async with _client(app) as client:
        initiated = await client.post("/api/pacts/pact_gate1/donation/initiate")
        assert initiated.status_code == 200, initiated.text
        assert initiated.json()["state"] == "awaiting_approval"
        pact = repo.get_pact("pact_gate1")
        assert pact is not None
        assert pact.spend_request_id == "sr_live_1"
        assert pact.status == PactStatus.donation_pending
        assert pact.stake_state == StakeState.executing

        pending = await client.post("/api/pacts/pact_gate1/donation/approve")
        assert pending.status_code == 409
        assert repo.get_pact("pact_gate1").status == PactStatus.donation_pending

        approved = await client.post("/api/pacts/pact_gate1/donation/approve")
        assert approved.status_code == 200, approved.text
        assert approved.json()["state"] == "donated"
        done = repo.get_pact("pact_gate1")
        assert done is not None
        assert done.status == PactStatus.donated
        assert done.stake_state == StakeState.executed

    attempts = repo.list_payment_attempts("pact_gate1")
    assert len(attempts) == 1
    assert attempts[0].provider_ref == "sr_live_1"
    assert attempts[0].status == "approved"


@pytest.mark.asyncio
async def test_live_test_mode_routes_through_the_real_subprocess_with_test_flag(tmp_path):
    # live_test must behave like live at the API level (shell link-cli, human-gated)
    # but against Link test credentials (--test), so the real path is exercisable
    # end-to-end with no real money.
    owner = "a@b.com"
    clock = _clock()
    db = str(tmp_path / "p.db")
    repo = Repository.connect(db)
    repo.init_schema()
    repo.save_pact(
        _failing_pact(clock, owner).model_copy(
            update={
                "status": PactStatus.donation_pending,
                "stake_state": StakeState.committed,
            }
        )
    )
    repo.save_link_account(
        LinkAccount(
            owner=owner,
            connected=True,
            funding_ref="pm_live_123",
            connected_at=clock.now(),
            payment_method_id="pm_live_123",
            auth_status="authenticated",
            checked_at=clock.now(),
        )
    )
    runner = _FakeRunner([
        {"id": "sr_t1", "status": "pending_approval"},  # create --test
        {"id": "sr_t1", "status": "pending_approval"},  # request-approval --test
    ])
    payment = LinkCliProvider(link_mode="live_test", runner=runner)
    settings = Settings(db_path=db, payment_mode="link_cli", link_mode="live_test")
    app = create_app(repo, TestLLMProvider(), payment, TokenStore(), clock, settings)

    async with _client(app) as client:
        r = await client.post("/api/pacts/pact_gate1/donation/initiate")
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "awaiting_approval"

    assert repo.get_pact("pact_gate1").spend_request_id == "sr_t1"
    assert "--test" in runner.calls[0][0]  # real subprocess path, test credentials


@pytest.mark.asyncio
async def test_live_donation_initiate_ambiguous_failure_parks_for_reconcile(tmp_path):
    owner = "a@b.com"
    clock = _clock()
    db = str(tmp_path / "p.db")
    repo = Repository.connect(db)
    repo.init_schema()
    repo.save_pact(
        _failing_pact(clock, owner).model_copy(
            update={
                "status": PactStatus.donation_pending,
                "stake_state": StakeState.committed,
            }
        )
    )
    repo.save_link_account(
        LinkAccount(
            owner=owner,
            connected=True,
            funding_ref="pm_live_123",
            connected_at=clock.now(),
            payment_method_id="pm_live_123",
            auth_status="authenticated",
            checked_at=clock.now(),
        )
    )

    class _AmbiguousRunner:
        # The create subprocess fires but never returns a verdict (timeout): we
        # cannot know whether Link created/charged the request.
        def run(self, args, timeout):
            raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)

    payment = LinkCliProvider(link_mode="live", runner=_AmbiguousRunner())
    settings = Settings(db_path=db, payment_mode="link_cli", link_mode="live")
    app = create_app(repo, TestLLMProvider(), payment, TokenStore(), clock, settings)

    async with _client(app) as client:
        r = await client.post("/api/pacts/pact_gate1/donation/initiate")
        assert r.status_code == 502, r.text

        parked = repo.get_pact("pact_gate1")
        assert parked is not None
        # Money may have moved → must NOT be terminal-failed, and the request was
        # never confirmed → no spend_request_id, stake flagged for reconcile.
        assert parked.status == PactStatus.donation_pending
        assert parked.stake_state == StakeState.error
        assert parked.spend_request_id is None

        # A retry must refuse to re-fire (link-cli has no idempotency key → would
        # risk a double charge).
        retry = await client.post("/api/pacts/pact_gate1/donation/initiate")
        assert retry.status_code == 409, retry.text

        state = await client.get("/api/pacts/pact_gate1/donation/status")
        assert state.json()["state"] == "reconcile"


@pytest.mark.asyncio
async def test_live_donation_initiate_is_idempotent_for_open_request(tmp_path):
    owner = "a@b.com"
    clock = _clock()
    db = str(tmp_path / "p.db")
    repo = Repository.connect(db)
    repo.init_schema()
    repo.save_pact(
        _failing_pact(clock, owner).model_copy(
            update={
                "status": PactStatus.donation_pending,
                "stake_state": StakeState.committed,
            }
        )
    )
    repo.save_link_account(
        LinkAccount(
            owner=owner,
            connected=True,
            funding_ref="pm_live_123",
            connected_at=clock.now(),
            payment_method_id="pm_live_123",
            auth_status="authenticated",
            checked_at=clock.now(),
        )
    )
    runner = _FakeRunner([{"id": "sr_live_once", "status": "pending_approval"}])
    payment = LinkCliProvider(link_mode="live", runner=runner)
    settings = Settings(db_path=db, payment_mode="link_cli", link_mode="live")
    app = create_app(repo, TestLLMProvider(), payment, TokenStore(), clock, settings)

    async with _client(app) as client:
        first = await client.post("/api/pacts/pact_gate1/donation/initiate")
        second = await client.post("/api/pacts/pact_gate1/donation/initiate")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    create_calls = [call for call in runner.calls if call[0][:3] == ["link-cli", "spend-request", "create"]]
    assert len(create_calls) == 1
    assert len(repo.list_payment_attempts("pact_gate1")) == 1


@pytest.mark.asyncio
async def test_live_donation_denied_does_not_mark_donated(tmp_path):
    owner = "a@b.com"
    clock = _clock()
    db = str(tmp_path / "p.db")
    repo = Repository.connect(db)
    repo.init_schema()
    repo.save_pact(
        _failing_pact(clock, owner).model_copy(
            update={
                "status": PactStatus.donation_pending,
                "stake_state": StakeState.committed,
            }
        )
    )
    repo.save_link_account(
        LinkAccount(
            owner=owner,
            connected=True,
            funding_ref="pm_live_123",
            connected_at=clock.now(),
            payment_method_id="pm_live_123",
            auth_status="authenticated",
            checked_at=clock.now(),
        )
    )
    runner = _FakeRunner([
        {"id": "sr_live_denied", "status": "pending_approval"},
        {"id": "sr_live_denied", "status": "denied"},
    ])
    payment = LinkCliProvider(link_mode="live", runner=runner)
    settings = Settings(db_path=db, payment_mode="link_cli", link_mode="live")
    app = create_app(repo, TestLLMProvider(), payment, TokenStore(), clock, settings)

    async with _client(app) as client:
        initiated = await client.post("/api/pacts/pact_gate1/donation/initiate")
        assert initiated.status_code == 200, initiated.text
        denied = await client.get("/api/pacts/pact_gate1/donation/status")
        assert denied.status_code == 200, denied.text
        assert denied.json()["state"] == "denied"

    pact = repo.get_pact("pact_gate1")
    assert pact is not None
    assert pact.status == PactStatus.donation_failed
    assert pact.stake_state == StakeState.error
    verdict = repo.get_verdict("pact_gate1")
    assert verdict is not None
    assert verdict.payment_action == "donation_failed"
    assert verdict.payment_ref == "sr_live_denied"
    attempts = repo.list_payment_attempts("pact_gate1")
    assert len(attempts) == 1
    assert attempts[0].status == "denied"

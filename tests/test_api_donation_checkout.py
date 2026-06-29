"""API: complete the donation by driving the charity page (Tier 2).

Uses an injected fake checkout runner so the endpoint is tested without a real
browser. Verifies the card-required guard, the pass-through of the helper result,
and that a real submit records a donation receipt.
"""

from datetime import datetime, timedelta, timezone
import json
import sys

import httpx
import pytest

from pact.anticheat import TokenStore
from pact.api import create_app, default_checkout_runner
from pact.clock import FixedClock
from pact.config import Settings
from pact.models import Modality, Pact, PactStatus, Rubric, StakeState
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository

OWNER = "owner@example.com"
NOW = datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc)


def _build(tmp_path, runner):
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    clock = FixedClock(NOW)
    settings = Settings(
        db_path=str(tmp_path / "pact.db"), artifacts_dir=str(tmp_path / "artifacts")
    )
    app = create_app(
        repo, TestLLMProvider(), TestLinkProvider(), TokenStore(), clock, settings,
        checkout_runner=runner,
    )
    return app, repo


def _donated_pact(pid: str, *, with_card: bool) -> Pact:
    return Pact(
        id=pid, owner=OWNER, original_prompt="x", title="Do the thing", goal="g",
        timezone="America/Los_Angeles", deadline_at=NOW - timedelta(days=2),
        target_count=3, recommended_stake_cents=2000, stake_amount_cents=2000,
        charity_id="charity_water", charity_url="https://www.charitywater.org/donate",
        rubric=Rubric(modality=Modality.photo, must_show=["x"], min_distinct_days=3, count_target=3),
        status=PactStatus.donated, stake_state=StakeState.executed,
        spend_request_id="test_sr", card_last4="4242" if with_card else None,
        card_artifact_path="/tmp/card.json" if with_card else None,
        created_at=NOW - timedelta(days=9), started_at=NOW - timedelta(days=9),
        verdict_at=NOW - timedelta(days=1),
    )


@pytest.mark.asyncio
async def test_checkout_requires_a_provisioned_card(tmp_path):
    app, repo = _build(tmp_path, runner=lambda *a, **k: {"status": "submitted", "submitted": True})
    repo.save_pact(_donated_pact("pact_nocard", with_card=False))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/pacts/pact_nocard/donation/checkout")
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_checkout_reached_card_step_does_not_record_receipt(tmp_path):
    captured = {}

    def runner(pact, settings, *, confirm):
        captured["confirm"] = confirm
        return {"status": "reached_card_step", "submitted": False, "amount_cents": 2000}

    app, repo = _build(tmp_path, runner=runner)
    repo.save_pact(_donated_pact("pact_step", with_card=True))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/pacts/pact_step/donation/checkout")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "reached_card_step"
        # default request does not confirm a real submit
        assert captured["confirm"] is False
        # no receipt recorded for a non-submit
        assert repo.get_donation_receipt("pact_step") is None


@pytest.mark.asyncio
async def test_checkout_submit_records_receipt(tmp_path):
    def runner(pact, settings, *, confirm):
        return {
            "status": "submitted", "submitted": True, "reference": "confirmed",
            "screenshot": "/tmp/shot.png", "note": "donation submitted",
        }

    app, repo = _build(tmp_path, runner=runner)
    repo.save_pact(_donated_pact("pact_done", with_card=True))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/pacts/pact_done/donation/checkout", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert r.json()["submitted"] is True

    receipt = repo.get_donation_receipt("pact_done")
    assert receipt is not None
    assert receipt.receipt_status == "provider_confirmed"
    assert receipt.receipt_source == "charity_checkout"
    # Single-use: the card ref is dropped so a retry can't re-charge it.
    assert repo.get_pact("pact_done").card_artifact_path is None


@pytest.mark.asyncio
async def test_checkout_declined_does_not_record_a_success_receipt(tmp_path):
    # A submitted-but-declined charge must NOT be recorded as a donation; otherwise
    # a failed charge masquerades as money that reached the charity.
    def runner(pact, settings, *, confirm):
        return {
            "status": "submitted", "submitted": True, "outcome": "declined",
            "reference": None, "note": "payment outcome=declined",
        }

    app, repo = _build(tmp_path, runner=runner)
    repo.save_pact(_donated_pact("pact_decl", with_card=True))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/pacts/pact_decl/donation/checkout", json={"confirm": True})
        assert r.status_code == 200, r.text

    receipt = repo.get_donation_receipt("pact_decl")
    # A decline records either nothing or an explicit failure — never a receipt that
    # reads as a completed donation (provider_confirmed / manual_receipt).
    assert receipt is None or receipt.receipt_status == "failed_or_reversed"


@pytest.mark.asyncio
async def test_checkout_is_idempotent_against_a_confirmed_donation(tmp_path):
    # Once confirmed, a second checkout must refuse — link-cli has no idempotency
    # key for the checkout, so a re-submit would be a second real charge.
    calls = {"n": 0}

    def runner(pact, settings, *, confirm):
        calls["n"] += 1
        return {"status": "submitted", "submitted": True, "reference": "confirmed"}

    app, repo = _build(tmp_path, runner=runner)
    repo.save_pact(_donated_pact("pact_idem", with_card=True))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/api/pacts/pact_idem/donation/checkout", json={"confirm": True})
        assert first.status_code == 200, first.text
        second = await client.post("/api/pacts/pact_idem/donation/checkout", json={"confirm": True})
        assert second.status_code == 409

    assert calls["n"] == 1  # the runner never ran a second charge


def test_default_checkout_runner_uses_frozen_sidecar_helper(monkeypatch, tmp_path):
    captured = {}

    class Proc:
        stdout = json.dumps({"status": "reached_card_step", "submitted": False})
        stderr = ""

    def fake_run(args, capture_output, text, timeout):
        captured["args"] = args
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["timeout"] = timeout
        return Proc()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/Applications/Pact.app/Contents/MacOS/pact-sidecar")
    monkeypatch.setattr("subprocess.run", fake_run)

    settings = Settings(
        db_path=str(tmp_path / "pact.db"),
        artifacts_dir=str(tmp_path / "artifacts"),
    )
    pact = _donated_pact("pact_frozen", with_card=True)

    result = default_checkout_runner(pact, settings, confirm=False)

    assert result["status"] == "reached_card_step"
    assert captured["args"][:2] == [
        "/Applications/Pact.app/Contents/MacOS/pact-sidecar",
        "--pact-charity-checkout",
    ]
    assert "-m" not in captured["args"]
    assert "4242424242424242" not in " ".join(captured["args"])

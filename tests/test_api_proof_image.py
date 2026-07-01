import io
import os
from datetime import datetime, timezone

import httpx
import pytest
from PIL import Image

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock
from pact.config import Settings
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository
from pact.models import TaskType


class CapturingVisionProvider(TestLLMProvider):
    def __init__(self):
        self.tasks = []

    def resolve(self, task):
        if task.type != TaskType.judge_proof:
            return super().resolve(task)
        self.tasks.append(task)
        return {
            "status": "passed",
            "reason": "vision reviewed stored artifact",
            "checklist": {"token_visible": True, "goal_visible": True},
        }


def _build(tmp_path, clock, provider=None, clock_mode="real"):
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    provider = provider or TestLLMProvider()
    payment = TestLinkProvider()
    tokens = TokenStore(ttl_minutes=10)
    settings = Settings(
        db_path=str(tmp_path / "pact.db"),
        artifacts_dir=str(tmp_path / "artifacts"),
        clock_mode=clock_mode,
    )
    app = create_app(repo, provider, payment, tokens, clock, settings)
    return app, repo, settings


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _png_bytes(color, size=(64, 64)) -> bytes:
    """A real, deterministic PNG. Distinct solid colors hash to distinct phashes."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


async def _draft_confirm_start(client, prompt):
    r = await client.post("/api/pacts/draft", json={"prompt": prompt})
    assert r.status_code == 200, r.text
    pact_id = r.json()["id"]
    r = await client.post(
        "/api/pacts",
        json={
            "pact_id": pact_id,
            "stake_amount_cents": 1500,
            "charity_id": "against_malaria_foundation",
            "consent_acknowledged": True,
        },
    )
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/pacts/{pact_id}/start")
    assert r.status_code == 200, r.text
    return pact_id


async def _token(client, pact_id):
    r = await client.post(f"/api/pacts/{pact_id}/proof-token")
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def _post_image(client, pact_id, token, data, content_ok=True):
    files = {"image": ("proof.png", data, "image/png")}
    form = {"token": token, "content_ok": str(content_ok).lower()}
    return await client.post(
        f"/api/pacts/{pact_id}/proofs/image", data=form, files=files
    )


@pytest.mark.asyncio
async def test_proof_token_returns_expiry_for_live_countdown(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(client, "run with a visible code")

        r = await client.post(f"/api/pacts/{pact_id}/proof-token")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token"].startswith("PACT-")
    assert body["expires_at"] == "2026-06-24T12:10:00+00:00"


@pytest.mark.asyncio
async def test_image_proof_held_ambiguous_without_vision_judge_but_persists(tmp_path):
    # No vision-capable agent is connected (plain TestLLMProvider), so an image
    # proof is HELD ambiguous for review rather than rubber-stamped as passed.
    # Token/phash/artifact are still computed and persisted server-side.
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, repo, settings = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(client, "do a thing 5x this week or $15 to charity")
        token = await _token(client, pact_id)

        r = await _post_image(client, pact_id, token, _png_bytes((10, 120, 200)))
        assert r.status_code == 200, r.text
        proof = r.json()
        assert proof["modality"] == "photo"
        assert proof["status"] == "ambiguous"
        assert proof["token_ok"] is True
        assert proof["dup_of"] is None
        assert proof["phash"] is not None
        # The artifact path is persisted, sits under the tmp artifacts dir, and exists.
        assert proof["artifact_path"] is not None
        assert settings.artifacts_dir in proof["artifact_path"]
        assert os.path.exists(proof["artifact_path"])

        # Server-truth: the proof is in the repo, attached to this pact.
        stored = repo.list_proofs(pact_id)
        assert len(stored) == 1
        assert stored[0].id == proof["id"]
        assert stored[0].status.value == "ambiguous"


@pytest.mark.asyncio
async def test_image_proof_auto_passes_in_demo_clock_mode(tmp_path):
    # Demo mode (scripted + simulated) accepts a coded photo without a vision agent
    # so the recorded check-in shows a clean PASS instead of "held for review".
    # A valid token and no duplicate are still required; production (clock_mode
    # "real") keeps the ambiguous behavior asserted above.
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, repo, _ = _build(tmp_path, clock, clock_mode="demo")
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(client, "do a thing 5x this week or $15 to charity")
        token = await _token(client, pact_id)

        r = await _post_image(client, pact_id, token, _png_bytes((10, 120, 200)))
        assert r.status_code == 200, r.text
        proof = r.json()
        assert proof["modality"] == "photo"
        assert proof["status"] == "passed"
        assert proof["token_ok"] is True
        assert proof["dup_of"] is None
        assert proof["phash"] is not None
        assert os.path.exists(proof["artifact_path"])

        stored = repo.list_proofs(pact_id)
        assert len(stored) == 1
        assert stored[0].status.value == "passed"


@pytest.mark.asyncio
async def test_duplicate_image_is_rejected(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, repo, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(client, "do a thing 5x this week or $15 to charity")

        # First submission of a given image: held ambiguous (no vision judge),
        # but still phashed so the duplicate check below has something to match.
        t1 = await _token(client, pact_id)
        img = _png_bytes((30, 180, 90))
        r1 = await _post_image(client, pact_id, t1, img)
        assert r1.status_code == 200, r1.text
        assert r1.json()["status"] == "ambiguous"
        first_phash = r1.json()["phash"]

        # Same image again, different (valid) token, next day: pHash dup -> failed.
        clock.advance(days=1)
        t2 = await _token(client, pact_id)
        r2 = await _post_image(client, pact_id, t2, img)
        assert r2.status_code == 200, r2.text
        proof2 = r2.json()
        assert proof2["status"] == "failed"
        assert proof2["token_ok"] is True
        assert proof2["dup_of"] == first_phash


@pytest.mark.asyncio
async def test_bad_token_image_fails(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(client, "do a thing 5x this week or $15 to charity")

        r = await _post_image(client, pact_id, "PACT-XX", _png_bytes((200, 40, 40)))
        assert r.status_code == 200, r.text
        proof = r.json()
        assert proof["status"] == "failed"
        assert proof["token_ok"] is False


@pytest.mark.asyncio
async def test_image_proof_judge_receives_stored_artifact_not_client_content_ok(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    provider = CapturingVisionProvider()
    app, repo, _ = _build(tmp_path, clock, provider=provider)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(client, "do a thing 5x this week or $15 to charity")
        token = await _token(client, pact_id)

        # The client-supplied content_ok field must not be trusted or forwarded.
        r = await _post_image(
            client,
            pact_id,
            token,
            _png_bytes((70, 110, 140)),
            content_ok=False,
        )
        assert r.status_code == 200, r.text
        proof = r.json()
        assert proof["status"] == "passed"

    assert provider.tasks, "provider should have reviewed the image proof"
    task = provider.tasks[-1]
    assert task.required_capability == "vision"
    assert "content_ok" not in task.input
    assert task.input["artifact_path"] == proof["artifact_path"]
    assert task.input["expected_token"] == token
    assert task.input["phash"] == proof["phash"]
    assert task.input["modality"] == "photo"
    assert task.input["pact_title"]
    assert task.input["pact_goal"]
    assert task.input["artifact"]["thumbnail_path"]
    assert task.input["artifact"]["mime_type"] == "image/png"
    assert task.input["artifact"]["size_bytes"] > 0

    reviews = repo.list_proof_reviews(proof["id"])
    assert len(reviews) == 1
    assert reviews[0].status.value == "passed"
    assert reviews[0].input_artifacts["artifact_path"] == proof["artifact_path"]
    assert reviews[0].checklist == {"token_visible": True, "goal_visible": True}

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


def _build(tmp_path, clock):
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    provider = TestLLMProvider()
    payment = TestLinkProvider()
    tokens = TokenStore(ttl_minutes=10)
    settings = Settings(
        db_path=str(tmp_path / "pact.db"),
        artifacts_dir=str(tmp_path / "artifacts"),
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
async def test_image_proof_valid_token_passes_and_persists(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, repo, settings = _build(tmp_path, clock)
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
        # The artifact path is persisted, sits under the tmp artifacts dir, and exists.
        assert proof["artifact_path"] is not None
        assert settings.artifacts_dir in proof["artifact_path"]
        assert os.path.exists(proof["artifact_path"])

        # Server-truth: the proof is in the repo, attached to this pact.
        stored = repo.list_proofs(pact_id)
        assert len(stored) == 1
        assert stored[0].id == proof["id"]
        assert stored[0].status.value == "passed"


@pytest.mark.asyncio
async def test_duplicate_image_is_rejected(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, repo, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(client, "do a thing 5x this week or $15 to charity")

        # First submission of a given image: passes.
        t1 = await _token(client, pact_id)
        img = _png_bytes((30, 180, 90))
        r1 = await _post_image(client, pact_id, t1, img)
        assert r1.status_code == 200, r1.text
        assert r1.json()["status"] == "passed"
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

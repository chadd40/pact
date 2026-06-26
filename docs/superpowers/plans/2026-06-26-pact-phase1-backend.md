# Pact Tier-2/3/4 Phase-1 (Backend + Local-First DX) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build the real backend capabilities the product (and the Phase-2 UI) need — real photo proof, a server-truth proofs endpoint, the `needs_review` safety path, a consent acknowledgment — plus local-first DX (one-process serve, a cheap SQLite write-lock, seeded coaching, favicon/launcher). **Local-first / OSS posture:** real capabilities + good local DX; SKIP production hardening (no auth, no durable/multi-worker token store, no TTL deletion, no compliance gates).

**Tech:** Python 3.11+, uv, FastAPI, Pydantic v2, SQLite, Pillow + imagehash, pytest + httpx. Builds on master (317 tests). `test_llm`/`test_link` stay the safe defaults; no real money/network in tests.

**Spec:** [`docs/superpowers/specs/2026-06-24-pact-design.md`](../specs/2026-06-24-pact-design.md) §6, §9.

**New surface:** `images.py` (EXIF strip + thumbnail + save + phash-from-bytes); `POST /api/pacts/{id}/proofs/image` (multipart) + `GET /api/pacts/{id}/proofs`; `ConfirmIn.consent_acknowledged` (required); `needs_review` in `submit_proof`/`settle`; a `threading.Lock` in `Repository`; FastAPI serving `web/dist`; seeded coaching + favicon + `scripts/dev.sh`.

**Order:** 1 (images) → 2 (image endpoint) → 3 (GET proofs) → 4 (needs_review) → 5 (consent + lock) → 6 (serve SPA) → 7 (seed coaching + polish). Tasks 2,3,5,6 touch api.py/main.py.

---

## Tasks


### Task 1: images.py: EXIF strip + thumbnail + save + phash-from-bytes

Real photo handling for image proofs: re-encode bytes through Pillow to drop EXIF/metadata (PII safety, spec §9), produce an EXIF-stripped thumbnail, persist both under the artifacts dir, and compute a perceptual hash directly from the *cleaned* bytes so dedup/judging hashes exactly what we stored. No TTL deletion (local-first posture). No network, no subprocess — pure Pillow + imagehash, both already in `pyproject.toml` dependencies.

**Files:**
- Create: `src/pact/images.py`
- Test: `tests/test_images.py`

Note on the contract: `strip_exif`/`make_thumbnail` must "Raise `ValueError` on non-image bytes." Pillow raises `PIL.UnidentifiedImageError` (a subclass of `OSError`, NOT `ValueError`) for junk bytes, so the implementation must catch it and re-raise as `ValueError`. Confirmed via probe: a fresh `Image.new(src.mode, src.size)` + `.paste(src)` + `save()` **without** an `exif=` kwarg drops all EXIF cleanly and avoids the deprecated `getdata()` path; `thumbnail((max_px, max_px))` caps the longest side at `max_px`; `imagehash.phash` is deterministic and equals `anticheat.phash_hex` for identical content.

---

- [ ] **Step 1: Write the failing test**

Create `tests/test_images.py` with real in-memory PIL images (one carrying an EXIF `ImageDescription` tag) and assert every behavior in the contract. No network, no fixtures on disk except a `tmp_path` artifacts dir.

```python
import io

import imagehash
import pytest
from PIL import Image, UnidentifiedImageError

from pact.anticheat import phash_hex
from pact.images import (
    make_thumbnail,
    phash_of_bytes,
    save_proof_image,
    strip_exif,
)


def _jpeg_with_exif(
    size: tuple[int, int] = (300, 200),
    color: tuple[int, int, int] = (123, 45, 67),
) -> bytes:
    """A JPEG whose EXIF carries a PII-ish ImageDescription tag (270)."""
    img = Image.new("RGB", size, color)
    exif = img.getexif()
    exif[270] = "secret-gps-and-name"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _png(
    size: tuple[int, int] = (120, 90),
    color: tuple[int, int, int] = (10, 200, 30),
) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_input_image_actually_carries_exif():
    # Guards the test itself: prove the source bytes have the tag we strip.
    src = Image.open(io.BytesIO(_jpeg_with_exif()))
    assert src.getexif().get(270) == "secret-gps-and-name"


def test_strip_exif_drops_metadata_and_preserves_format():
    cleaned = strip_exif(_jpeg_with_exif())
    out = Image.open(io.BytesIO(cleaned))
    assert dict(out.getexif()) == {}
    assert out.format == "JPEG"
    assert out.size == (300, 200)


def test_strip_exif_preserves_png_format():
    cleaned = strip_exif(_png())
    out = Image.open(io.BytesIO(cleaned))
    assert out.format == "PNG"
    assert dict(out.getexif()) == {}


def test_strip_exif_rejects_non_image_bytes():
    with pytest.raises(ValueError):
        strip_exif(b"this is not an image")


def test_make_thumbnail_caps_longest_side_and_strips_exif():
    thumb_bytes = make_thumbnail(_jpeg_with_exif(size=(800, 400)), max_px=256)
    thumb = Image.open(io.BytesIO(thumb_bytes))
    assert max(thumb.size) <= 256
    # Aspect ratio preserved: 800x400 -> 256x128.
    assert thumb.size == (256, 128)
    assert dict(thumb.getexif()) == {}


def test_make_thumbnail_does_not_upscale_small_images():
    small = _png(size=(100, 80))
    thumb = Image.open(io.BytesIO(make_thumbnail(small, max_px=256)))
    assert thumb.size == (100, 80)


def test_make_thumbnail_rejects_non_image_bytes():
    with pytest.raises(ValueError):
        make_thumbnail(b"nope", max_px=256)


def test_save_proof_image_writes_both_files_under_pact_dir(tmp_path):
    data = _jpeg_with_exif()
    image_path, thumb_path = save_proof_image(
        str(tmp_path), "pact_abc123", "proof_def456", data
    )
    import os

    assert os.path.exists(image_path)
    assert os.path.exists(thumb_path)
    # Both live under artifacts_dir/<pact_id>/.
    pact_dir = os.path.join(str(tmp_path), "pact_abc123")
    assert os.path.commonpath([pact_dir, image_path]) == pact_dir
    assert os.path.commonpath([pact_dir, thumb_path]) == pact_dir
    assert image_path != thumb_path
    # Stored full image is EXIF-stripped.
    saved = Image.open(image_path)
    assert dict(saved.getexif()) == {}
    # Stored thumb is a real, smaller-or-equal image.
    saved_thumb = Image.open(thumb_path)
    assert max(saved_thumb.size) <= 256


def test_save_proof_image_creates_missing_dirs(tmp_path):
    nested = tmp_path / "does" / "not" / "exist"
    image_path, thumb_path = save_proof_image(
        str(nested), "pact_x", "proof_y", _png()
    )
    import os

    assert os.path.exists(image_path)
    assert os.path.exists(thumb_path)


def test_phash_of_bytes_is_deterministic():
    data = _jpeg_with_exif()
    assert phash_of_bytes(data) == phash_of_bytes(data)


def test_phash_of_bytes_matches_anticheat_for_same_content(tmp_path):
    data = _jpeg_with_exif()
    p = tmp_path / "same.jpg"
    p.write_bytes(data)
    assert phash_of_bytes(data) == phash_hex(str(p))


def test_phash_of_bytes_matches_imagehash_directly():
    data = _png()
    expected = str(imagehash.phash(Image.open(io.BytesIO(data))))
    assert phash_of_bytes(data) == expected


def test_phash_of_bytes_rejects_non_image_bytes():
    with pytest.raises(ValueError):
        phash_of_bytes(b"definitely not a png")
```

- [ ] **Step 2: Run the test — expect FAIL**

```
uv run pytest tests/test_images.py -v
```

Expected: collection-time `ModuleNotFoundError: No module named 'pact.images'` (or `ImportError` on the four names), so every test errors. This confirms the test file is wired to the not-yet-existing module.

- [ ] **Step 3: Write the minimal implementation**

Create `src/pact/images.py`. The single private helper `_load` centralizes the non-image -> `ValueError` conversion so the contract's "Raises ValueError on non-image bytes" holds for `strip_exif`, `make_thumbnail`, and `phash_of_bytes` alike. `_reencode` builds a fresh same-mode image and pastes pixels in, then saves with no `exif=` kwarg — this drops all EXIF/metadata while preserving the source format (verified: empty `getexif()`, `format` unchanged, no deprecated `getdata()` call).

```python
from __future__ import annotations

import io
import os

import imagehash
from PIL import Image, UnidentifiedImageError

_DEFAULT_FORMAT = "PNG"


def _load(data: bytes) -> Image.Image:
    """Open image bytes, normalizing any decode failure to ValueError.

    Pillow raises UnidentifiedImageError (an OSError subclass) for junk bytes;
    the contract requires ValueError, so we translate here. `.load()` forces the
    decode eagerly so truncated/corrupt payloads fail now, not later.
    """
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        return img
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError(f"not a decodable image: {exc}") from exc


def _reencode(img: Image.Image) -> bytes:
    """Re-encode an image into a fresh same-mode canvas, dropping all metadata.

    Pasting into a new Image() and saving without an exif= kwarg strips EXIF and
    other metadata while preserving the original format (default PNG).
    """
    fmt = img.format or _DEFAULT_FORMAT
    clean = Image.new(img.mode, img.size)
    clean.paste(img)
    out = io.BytesIO()
    clean.save(out, format=fmt)
    return out.getvalue()


def strip_exif(data: bytes) -> bytes:
    """Return EXIF/metadata-free image bytes, preserving the source format.

    Raises ValueError on non-image bytes.
    """
    return _reencode(_load(data))


def make_thumbnail(data: bytes, max_px: int = 256) -> bytes:
    """Return a downscaled, EXIF-stripped copy whose longest side <= max_px.

    Never upscales (Image.thumbnail only shrinks). Raises ValueError on non-image
    bytes.
    """
    img = _load(data)
    fmt = img.format or _DEFAULT_FORMAT
    clean = Image.new(img.mode, img.size)
    clean.paste(img)
    clean.thumbnail((max_px, max_px))
    out = io.BytesIO()
    clean.save(out, format=fmt)
    return out.getvalue()


def save_proof_image(
    artifacts_dir: str, pact_id: str, proof_id: str, data: bytes
) -> tuple[str, str]:
    """Persist an EXIF-stripped full image + a thumbnail under
    artifacts_dir/<pact_id>/, creating directories as needed.

    Returns (image_path, thumb_path). Raises ValueError on non-image bytes.
    """
    clean_full = strip_exif(data)
    thumb = make_thumbnail(data)

    ext = (Image.open(io.BytesIO(clean_full)).format or _DEFAULT_FORMAT).lower()
    if ext == "jpeg":
        ext = "jpg"

    pact_dir = os.path.join(artifacts_dir, pact_id)
    os.makedirs(pact_dir, exist_ok=True)

    image_path = os.path.join(pact_dir, f"{proof_id}.{ext}")
    thumb_path = os.path.join(pact_dir, f"{proof_id}_thumb.{ext}")
    with open(image_path, "wb") as f:
        f.write(clean_full)
    with open(thumb_path, "wb") as f:
        f.write(thumb)
    return image_path, thumb_path


def phash_of_bytes(data: bytes) -> str:
    """Perceptual hash computed directly from image bytes.

    Complements anticheat.phash_hex (which takes a path); identical pixel content
    yields an identical hash. Raises ValueError on non-image bytes.
    """
    return str(imagehash.phash(_load(data)))
```

- [ ] **Step 4: Run the test — expect PASS**

```
uv run pytest tests/test_images.py -v
```

Expected: all tests pass. Then confirm no regression across the suite:

```
uv run pytest -q
```

Expected: 317 prior tests + the new `test_images.py` tests all pass (no existing module imports `pact.images` yet, so this is purely additive).

- [ ] **Step 5: Commit**

```
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' add src/pact/images.py tests/test_images.py
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' commit -m "feat(images): EXIF strip + thumbnail + save + phash-from-bytes

Real photo handling for image proofs (spec §9 PII safety, local-first):
re-encode through Pillow to drop EXIF/metadata, emit an EXIF-stripped
thumbnail, persist both under artifacts_dir/<pact_id>/, and hash the
cleaned bytes (phash_of_bytes matches anticheat.phash_hex for identical
content). Non-image bytes raise ValueError. No TTL deletion, no network.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

No existing signatures change in this task — `src/pact/images.py` is a brand-new module and nothing imports it yet, so there are no call sites to update. (The image-proof endpoint in `api.py` that consumes these functions is a later task.)


### Task 2: Image proof endpoint (multipart)

Adds `POST /api/pacts/{id}/proofs/image` so the UI can upload a real photo as proof. The endpoint reads the uploaded bytes, strips EXIF, persists a clean full image + thumbnail under `settings.artifacts_dir`, hashes the *cleaned* bytes, and runs the real `submit_proof` lifecycle (token verify, dedup, judge) with `image_path` pointing at the saved file. The existing JSON `POST /api/pacts/{id}/proofs` (text/log) stays untouched.

**Depends on Task 1** (`src/pact/images.py`): this task imports `strip_exif`, `save_proof_image`, and `phash_of_bytes` from it. Do Task 1 first.

**Files:**
- Modify: `src/pact/api.py` (add the multipart endpoint; add `python-multipart` dependency)
- Modify: `pyproject.toml` (declare `python-multipart` — added via `uv add`, do not hand-edit)
- Test: `tests/test_api_proof_image.py` (create)

> Note on dedup phash. `submit_proof` (lifecycle.py) re-hashes the file at `image_path` via `anticheat.phash_hex(path)` and dedups against `prior_phashes`. Because Task 1's `save_proof_image` writes the EXIF-stripped bytes to disk, the path we pass already contains the cleaned bytes, so `phash_hex(saved_path)` equals `phash_of_bytes(clean_bytes)`. We still compute `phash_of_bytes(clean)` in the endpoint and assert/return consistency, but the dedup that `submit_proof` performs is over the cleaned on-disk bytes by construction — no stale-EXIF hash leaks in. `submit_proof` returns the `Proof` with `artifact_path=image_path` (the saved full-image path) already set, so no post-hoc rewrite is needed.

---

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_proof_image.py`. Builds the app exactly like `tests/test_api_flow.py` (`create_app(repo, provider, payment, tokens, clock, settings)` over `httpx.ASGITransport`), points `Settings.artifacts_dir` at a tmp dir, drafts→confirms→starts a pact, then posts real PNG bytes as multipart. Covers: (a) valid token + fresh image → `passed`/`token_ok`, artifact persisted on disk; (b) a second, perceptually-identical image with a fresh token → `failed` with `dup_of` set; (c) a bad token → `failed` and `token_ok=false`.

```python
import io
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
            "charity_id": "world_central_kitchen",
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
```

Add the missing `os` import at the very top of the file (used by `test_image_proof_valid_token_passes_and_persists`):

```python
import os
```

(Place it as the first import line so the file reads `import io`, `import os`, then the rest.)

- [ ] **Step 2: Run the test — expect FAIL**

```bash
uv run pytest tests/test_api_proof_image.py -v
```

Expected: FAIL. Most likely `404 Not Found` on `POST /api/pacts/{id}/proofs/image` (route doesn't exist yet), or a `500` / startup error about `python-multipart` not being installed (FastAPI needs it to parse `Form`/`UploadFile`). Both confirm the endpoint and its multipart dependency are not in place.

- [ ] **Step 3: Add the `python-multipart` dependency**

FastAPI cannot parse `Form(...)` / `UploadFile` multipart bodies without `python-multipart`. It is currently not installed. Add it as a real runtime dependency (do NOT hand-edit `pyproject.toml`):

```bash
uv add python-multipart
```

Confirm it resolved:

```bash
uv run python -c "import importlib.util as u; assert u.find_spec('multipart'), 'python-multipart missing'; print('python-multipart OK')"
```

- [ ] **Step 4: Implement the endpoint (minimal)**

Edit `src/pact/api.py`.

First extend the imports. Add `File`, `Form`, `UploadFile` to the existing FastAPI import, and import the Task-1 image helpers. Change:

```python
from fastapi import FastAPI, HTTPException
```

to:

```python
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
```

And add this import alongside the other `from pact....` imports (e.g. just after the `from pact.demo import ...` block):

```python
from pact.images import phash_of_bytes, save_proof_image, strip_exif
```

Then add the new route. Insert it immediately AFTER the existing JSON `proofs` route (the `@app.post("/api/pacts/{pact_id}/proofs")` handler ends at `return proof.model_dump(mode="json")` around line 194) and BEFORE `@app.post("/api/pacts/{pact_id}/freeze")`:

```python
    @app.post("/api/pacts/{pact_id}/proofs/image")
    async def proofs_image(
        pact_id: str,
        token: str = Form(...),
        content_ok: bool = Form(True),
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
        image_path, _thumb_path = save_proof_image(
            settings.artifacts_dir, pact.id, proof_id, clean
        )

        # Dedup over the CLEANED bytes. save_proof_image wrote the EXIF-stripped
        # bytes to image_path, so submit_proof's phash_hex(image_path) hashes the
        # same bytes as phash_of_bytes(clean) here.
        _ = phash_of_bytes(clean)
        prior_proofs = repo.list_proofs(pact_id)
        prior_phashes = [p.phash for p in prior_proofs if p.phash is not None]

        try:
            proof = submit_proof(
                pact,
                Modality.photo,
                token,
                content_ok,
                image_path,
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
```

Notes on why this is correct against the frozen signatures:
- `submit_proof(pact, modality, token, content_ok, image_path, tokens, provider, clock, prior_phashes=...)` is the exact lifecycle.py signature; it sets `Proof.artifact_path=image_path` (the saved full-image path), computes `phash` via `phash_hex(image_path)`, and sets `dup_of` when `find_duplicate` matches a prior phash — so `dup_of` equals the *matched prior phash string* (this is why the test asserts `proof2["dup_of"] == first_phash`).
- `new_pact_id`, `Modality`, `TransitionError`, `submit_proof`, `repo`, `provider`, `tokens`, `clock`, `settings` are all already imported / in scope inside `create_app`.
- The JSON `/proofs` route is unchanged.

- [ ] **Step 5: Run the test — expect PASS**

```bash
uv run pytest tests/test_api_proof_image.py -v
```

Expected: PASS — all three tests green (valid passes + persists, duplicate fails with `dup_of`, bad token fails).

- [ ] **Step 6: Run the full suite — expect no regressions**

```bash
uv run pytest -q
```

Expected: the prior 317 pass, plus the 3 new tests from this task (and any from Task 1), all green. The new multipart route and the `python-multipart` dependency do not touch existing routes.

- [ ] **Step 7: Commit**

```bash
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' add src/pact/api.py tests/test_api_proof_image.py pyproject.toml uv.lock
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' commit -m "$(cat <<'EOF'
feat(api): image proof endpoint (multipart upload + EXIF-strip + dedup)

Add POST /api/pacts/{id}/proofs/image: read UploadFile bytes, strip EXIF,
persist clean full image + thumbnail under settings.artifacts_dir, then run
the real submit_proof lifecycle (token verify, pHash dedup over prior proofs,
judge) with image_path pointing at the saved file. Returns the persisted Proof.
JSON /proofs (text/log) is unchanged. Adds python-multipart for multipart parsing.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

**Call sites / signature impact:** none changed. This task only *adds* a route and a dependency; it does not alter `submit_proof`, `ConfirmIn`, or any existing handler. (The `ConfirmIn.consent_acknowledged` change lives in a separate task and is not touched here.)


### Task 3: GET proofs endpoint (server-truth)

Adds a read-only `GET /api/pacts/{pact_id}/proofs` route so the UI can render real proof progress from the backend's source of truth. The repository's `list_proofs` does not order rows, so the endpoint sorts by `received_at` in Python before serializing.

**Files:**
- Modify: `/Users/chadd_mini/hermes-projects/pact/src/pact/api.py`
- Create (test): `/Users/chadd_mini/hermes-projects/pact/tests/test_api_get_proofs.py`

No existing signatures change (this task only adds a new GET route; `ConfirmIn`, `submit_proof`, etc. are untouched). The existing JSON `POST /api/pacts/{pact_id}/proofs` route is unchanged; we add a sibling `GET` on the same path.

---

- [ ] **Step 1: Write the failing test**

Create `/Users/chadd_mini/hermes-projects/pact/tests/test_api_get_proofs.py` with the complete contents below. It builds the app over `ASGITransport` (no network), drafts/confirms/starts a pact, submits two valid proofs across two distinct days (advancing the `FixedClock` between them so `received_at` and `day_bucket` differ), then asserts `GET /api/pacts/{id}/proofs` returns both proofs ordered by `received_at` with the expected `status`/`day_bucket` fields. Also asserts an empty list for a fresh pact with no proofs, and a 404 for a missing pact.

```python
from datetime import datetime, timezone

import httpx
import pytest

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
    settings = Settings(db_path=str(tmp_path / "pact.db"))
    app = create_app(repo, provider, payment, tokens, clock, settings)
    return app, repo


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _draft_confirm_start(client, prompt):
    r = await client.post("/api/pacts/draft", json={"prompt": prompt})
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

    r = await client.post(f"/api/pacts/{pact_id}/start")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"
    return pact_id


async def _submit_valid_proof(client, pact_id):
    r = await client.post(f"/api/pacts/{pact_id}/proof-token")
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    r = await client.post(
        f"/api/pacts/{pact_id}/proofs",
        json={
            "modality": "text",
            "token": token,
            "content_ok": True,
            "image_path": None,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_get_proofs_returns_two_in_order(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(
            client, "do a thing 5x this week or $15 to charity"
        )

        first = await _submit_valid_proof(client, pact_id)
        clock.advance(days=1)
        second = await _submit_valid_proof(client, pact_id)

        r = await client.get(f"/api/pacts/{pact_id}/proofs")
        assert r.status_code == 200, r.text
        proofs = r.json()
        assert isinstance(proofs, list)
        assert len(proofs) == 2

        # Ordered by received_at ascending: the first-submitted proof comes first.
        assert proofs[0]["id"] == first["id"]
        assert proofs[1]["id"] == second["id"]
        received = [p["received_at"] for p in proofs]
        assert received == sorted(received)

        # Server-truth fields the UI relies on.
        for p in proofs:
            assert p["pact_id"] == pact_id
            assert p["status"] == "passed"
        # Distinct days because the clock advanced one day between submissions.
        assert proofs[0]["day_bucket"] != proofs[1]["day_bucket"]


@pytest.mark.asyncio
async def test_get_proofs_empty_for_fresh_pact(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        pact_id = await _draft_confirm_start(
            client, "do a thing 5x this week or $15 to charity"
        )
        r = await client.get(f"/api/pacts/{pact_id}/proofs")
        assert r.status_code == 200, r.text
        assert r.json() == []


@pytest.mark.asyncio
async def test_get_proofs_404_for_missing_pact(tmp_path):
    clock = FixedClock(datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))
    app, _ = _build(tmp_path, clock)
    async with _client(app) as client:
        r = await client.get("/api/pacts/pact_missing/proofs")
        assert r.status_code == 404, r.text
        assert r.json()["detail"] == "pact not found"
```

- [ ] **Step 2: Run the test — expect FAIL**

```
uv run pytest tests/test_api_get_proofs.py -v
```

Expected: `test_get_proofs_returns_two_in_order` and `test_get_proofs_empty_for_fresh_pact` FAIL because no `GET /api/pacts/{pact_id}/proofs` route exists yet — FastAPI matches the path to the dynamic `GET /api/pacts/{pact_id}` route (treating `proofs` as a pact id), returning **404** with detail `"pact not found"` (so the JSON for "two in order" / "empty" assertions never holds). The `test_get_proofs_404_for_missing_pact` case may incidentally pass for the wrong reason; that's fine — it must still pass after the real route exists.

- [ ] **Step 3: Add the GET proofs route (minimal implementation)**

In `/Users/chadd_mini/hermes-projects/pact/src/pact/api.py`, insert a new GET route immediately after the existing `proofs` POST handler (which ends at the `return proof.model_dump(mode="json")` line for `POST /api/pacts/{pact_id}/proofs`). The route reads server-truth from the repo, sorts by `received_at` (the repo does NOT order proofs), and serializes with `model_dump(mode="json")` to match every other route.

Add exactly this block (place it directly below the closing of the `proofs` POST function, before the `@app.post("/api/pacts/{pact_id}/freeze")` definition):

```python
    @app.get("/api/pacts/{pact_id}/proofs")
    def list_proofs_endpoint(pact_id: str):
        # Server-truth proof list for the UI: 404 if the pact is unknown, else the
        # pact's proofs ordered by received_at (the repo returns them unordered).
        _require(pact_id)
        proofs_list = sorted(
            repo.list_proofs(pact_id), key=lambda p: p.received_at
        )
        return [p.model_dump(mode="json") for p in proofs_list]
```

- [ ] **Step 4: Run the test — expect PASS**

```
uv run pytest tests/test_api_get_proofs.py -v
```

Expected: all three tests PASS. Then run the full suite to confirm no regression (the new GET route must not shadow the existing `GET /api/pacts/{pact_id}` route — FastAPI's literal-suffix path `/proofs` is more specific and both coexist):

```
uv run pytest -q
```

Expected: the previously-passing 317 tests still pass, plus the 3 new ones (320 total).

- [ ] **Step 5: Commit**

```
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' add src/pact/api.py tests/test_api_get_proofs.py
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' commit -m "$(cat <<'EOF'
feat(api): GET /api/pacts/{id}/proofs server-truth proof list

Add a read-only GET proofs endpoint that returns a pact's proofs ordered
by received_at (model_dump json), 404 when the pact is missing. Lets the
UI render real proof progress from the backend source of truth instead of
optimistic client state.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```


### Task 4: needs_review on resolver error + ambiguous-decisive

**Files:**
- Modify: `src/pact/lifecycle.py` (`submit_proof` resolver-error guard; `settle` needs_review trigger)
- Test: `tests/test_needs_review.py` (create)

**Context (verified against source):**
- `submit_proof(pact, modality, token, content_ok, image_path, tokens, provider, clock, prior_phashes=None) -> Proof` builds a judge task via `make_reasoning_task(TaskType.judge_proof, ...)` then calls `result = provider.resolve(task)` and reads `result["status"]`, `result["reason"]`, `result["checklist"]`. The resolver call sits at `lifecycle.py:205` and is currently unguarded — a raising provider crashes the request.
- `settle(pact, proofs, clock, payment, settings) -> tuple[Pact, Verdict]` at `lifecycle.py:307`. `_valid_count` returns `count_distinct_valid_days(proofs)` (distinct `day_bucket` of `ProofStatus.passed` proofs) when `pact.distinct_days` is True (default), else a raw passed count. The FAIL branch sets `pact.status = PactStatus.failed`, opens `dispute_window_closes_at`, sets `verdict_at`, payment_action `none`.
- `ProofStatus(passed, failed, ambiguous)` and `PactStatus.needs_review` already exist (models.py:15, 37). `ALLOWED_TRANSITIONS` already permits `evaluating -> needs_review` and `needs_review -> {succeeded, failed, evaluating}` (lifecycle.py:31, 33-37), so no transition-map change is needed.
- `_TERMINAL_STATUSES` (lifecycle.py:259) does NOT include `needs_review`, so a re-`settle` after the ambiguous proofs are re-judged proceeds through the normal valid-count logic — exactly the idempotent re-settle the contract wants.
- `count_distinct_valid_days` counts only `passed`. We need an **ambiguous-distinct-days** helper for the flip check; add it inline in `settle` (count distinct `day_bucket` among `ProofStatus.ambiguous` proofs, excluding days already counted as passed so a passed+ambiguous same-day pair can't double-count).

No existing signatures change. The existing `tests/test_lifecycle_settle.py` only uses passed/failed proofs (never ambiguous) and never asserts on `needs_review`, so its SUCCESS and clean-FAIL assertions stay green unchanged — no edits required there.

---

- [ ] **Step 1: Write the failing test**

Create `tests/test_needs_review.py`. It exercises (a) the resolver-error guard in `submit_proof` and (b) the needs_review trigger in `settle`, using a raising fake provider and the same `SpyPaymentProvider` pattern as the existing settle test.

```python
from datetime import datetime, timedelta, timezone

import pytest

from pact.anticheat import TokenStore
from pact.clock import FixedClock
from pact.config import load_settings
from pact.lifecycle import close_dispute_window, settle, submit_proof
from pact.models import (
    Modality,
    Pact,
    PactStatus,
    PaymentAction,
    Proof,
    ProofStatus,
    Rubric,
    StakeState,
)
from pact.payment import PaymentResult, TestLinkProvider


class SpyPaymentProvider:
    """Counts create_donation calls; delegates to a real TestLinkProvider."""

    def __init__(self):
        self.calls = 0
        self._inner = TestLinkProvider()

    def create_donation(self, pact: Pact, idempotency_key: str) -> PaymentResult:
        self.calls += 1
        self.last_idempotency_key = idempotency_key
        return self._inner.create_donation(pact, idempotency_key)


class RaisingProvider:
    """Reasoning provider whose resolve() always raises (resolver unavailable)."""

    def capabilities(self) -> set[str]:
        return {"text", "vision"}

    def resolve(self, task):
        raise RuntimeError("resolver boom")


def _rubric() -> Rubric:
    return Rubric(
        modality=Modality.photo,
        must_show=["evidence of the activity"],
        min_distinct_days=3,
        count_target=3,
    )


def _pact(clock: FixedClock, target: int = 3) -> Pact:
    now = clock.now()
    return Pact(
        id="pact_abc123",
        owner="colehaddad40@gmail.com",
        original_prompt="do the thing 3x or $5 to charity",
        title="Do the thing 3x",
        goal="Complete the thing on 3 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=now,
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


def _proof(idx: int, day: str, status: ProofStatus, received: datetime) -> Proof:
    return Proof(
        id=f"proof_{idx}",
        pact_id="pact_abc123",
        modality=Modality.photo,
        received_at=received,
        day_bucket=day,
        token_ok=True,
        status=status,
    )


def _proofs(passed: int, ambiguous: int, base: datetime) -> list[Proof]:
    """`passed` passed proofs then `ambiguous` ambiguous proofs, each on a distinct day."""
    out: list[Proof] = []
    day_i = 0
    for _ in range(passed):
        day = f"2026-06-{10 + day_i:02d}"
        out.append(_proof(day_i, day, ProofStatus.passed, base + timedelta(days=day_i)))
        day_i += 1
    for _ in range(ambiguous):
        day = f"2026-06-{10 + day_i:02d}"
        out.append(_proof(day_i, day, ProofStatus.ambiguous, base + timedelta(days=day_i)))
        day_i += 1
    return out


# ── (a) submit_proof: resolver error -> ambiguous proof, no crash ──────────────


def test_submit_proof_resolver_error_records_ambiguous_no_crash():
    clock = FixedClock(datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc))
    pact = _pact(clock, target=3)
    tokens = TokenStore()
    token = tokens.issue(pact.id, clock)

    proof = submit_proof(
        pact,
        Modality.text,
        token,
        True,
        None,  # no image -> no PIL, deterministic
        tokens,
        RaisingProvider(),
        clock,
        prior_phashes=None,
    )

    assert proof.status == ProofStatus.ambiguous
    assert proof.judge_reason == "judging unavailable (resolver error)"
    assert proof.token_ok is True  # token verification happened before the judge call


# ── (b) settle: ambiguous-decisive FAIL -> needs_review (no donation/window) ────


def test_settle_ambiguous_decisive_sets_needs_review_no_donation():
    # target 4, 3 passed + 1 ambiguous distinct day: 3 < 4 <= 3+1 -> flippable.
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    pact = _pact(clock, target=4)
    proofs = _proofs(3, 1, datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc))
    payment = SpyPaymentProvider()

    new_pact, verdict = settle(pact, proofs, clock, payment, settings)

    assert new_pact.status == PactStatus.needs_review
    assert payment.calls == 0  # never donates from needs_review
    assert new_pact.spend_request_id is None
    assert new_pact.stake_state == StakeState.committed  # stake untouched
    assert new_pact.dispute_window_closes_at is None  # no dispute window opened
    assert verdict.status == PactStatus.needs_review
    assert verdict.valid_proof_count == 3
    assert verdict.target_count == 4
    assert verdict.payment_action == PaymentAction.none
    assert verdict.payment_ref is None


def test_settle_ambiguous_not_decisive_is_clean_fail():
    # target 5, 3 passed + 1 ambiguous: 3 < 5 but 5 > 3+1 -> ambiguous can't flip it.
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    pact = _pact(clock, target=5)
    proofs = _proofs(3, 1, datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc))
    payment = SpyPaymentProvider()

    failed, verdict = settle(pact, proofs, clock, payment, settings)

    # Clean FAIL: window opens, no needs_review, no money yet.
    assert failed.status == PactStatus.failed
    assert failed.dispute_window_closes_at is not None
    assert payment.calls == 0
    assert verdict.status == PactStatus.failed
    assert verdict.payment_action == PaymentAction.none

    # And after the window closes it still donates exactly once (clean-FAIL unchanged).
    clock.advance(hours=settings.dispute_grace_hours + 1)
    donated, dverdict = close_dispute_window(failed, proofs, clock, payment, settings)
    assert donated.status == PactStatus.donated
    assert payment.calls == 1
    assert dverdict.payment_action == PaymentAction.donation_executed


def test_settle_needs_review_then_rejudged_proceeds_normally():
    # Re-settle after the ambiguous proof is re-judged: passed -> success; failed -> clean fail.
    clock = FixedClock(datetime(2026, 6, 28, 23, 59, tzinfo=timezone.utc))
    settings = load_settings({})
    base = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
    payment = SpyPaymentProvider()

    pact = _pact(clock, target=4)
    proofs = _proofs(3, 1, base)
    paused, _ = settle(pact, proofs, clock, payment, settings)
    assert paused.status == PactStatus.needs_review

    # Ambiguous proof re-judged to passed -> now 4/4 -> success on re-settle.
    proofs[3].status = ProofStatus.passed
    resettled, verdict = settle(paused, proofs, clock, payment, settings)
    assert resettled.status == PactStatus.succeeded
    assert resettled.stake_state == StakeState.released
    assert payment.calls == 0
    assert verdict.status == PactStatus.succeeded
    assert verdict.valid_proof_count == 4
```

- [ ] **Step 2: Run the test — expect FAIL**

```
uv run pytest tests/test_needs_review.py -v
```

Expected FAIL: `test_submit_proof_resolver_error_records_ambiguous_no_crash` errors with `RuntimeError: resolver boom` (the unguarded `provider.resolve` call propagates); the needs_review tests fail because `settle` currently returns `PactStatus.failed` with a dispute window instead of `PactStatus.needs_review`.

- [ ] **Step 3: Implement the resolver-error guard in `submit_proof`**

In `src/pact/lifecycle.py`, replace the bare resolve-and-build block at the end of `submit_proof` (currently `result = provider.resolve(task)` followed by the `return Proof(...)`) with a guarded version that, on any resolver exception, builds the Proof with `status=ProofStatus.ambiguous` and `judge_reason="judging unavailable (resolver error)"` instead of crashing.

Replace this exact block:

```python
    result = provider.resolve(task)

    return Proof(
        id=new_pact_id(pact.id + token + now.isoformat()).replace("pact_", "proof_"),
        pact_id=pact.id,
        modality=modality,
        received_at=now,
        day_bucket=bucket,
        token_issued=token,
        token_ok=token_ok,
        phash=phash,
        dup_of=dup_of,
        artifact_path=image_path,
        status=ProofStatus(result["status"]),
        judge_reason=result["reason"],
        judge_checklist=result["checklist"],
    )
```

with:

```python
    try:
        result = provider.resolve(task)
        proof_status = ProofStatus(result["status"])
        judge_reason = result["reason"]
        judge_checklist = result["checklist"]
    except Exception:
        # Money-safety: if the resolver is unavailable/errors, do NOT crash the
        # request and do NOT silently pass/fail. Park the proof as ambiguous so a
        # later re-judge can resolve it; settle() treats decisive ambiguity as
        # needs_review and never donates off an unjudged proof.
        proof_status = ProofStatus.ambiguous
        judge_reason = "judging unavailable (resolver error)"
        judge_checklist = {}

    return Proof(
        id=new_pact_id(pact.id + token + now.isoformat()).replace("pact_", "proof_"),
        pact_id=pact.id,
        modality=modality,
        received_at=now,
        day_bucket=bucket,
        token_issued=token,
        token_ok=token_ok,
        phash=phash,
        dup_of=dup_of,
        artifact_path=image_path,
        status=proof_status,
        judge_reason=judge_reason,
        judge_checklist=judge_checklist,
    )
```

- [ ] **Step 4: Implement the needs_review trigger in `settle`**

In `src/pact/lifecycle.py`, in `settle`, between the SUCCESS branch (`if valid >= pact.target_count:` ... `return ...`) and the FAIL/defer block (`pact.status = PactStatus.failed`), insert the ambiguous-decisive check. Compute the distinct ambiguous days that aren't already counted as valid; if those could lift `valid` to `target`, park the pact in `needs_review` with no donation and no window.

Insert this block immediately after the SUCCESS branch's closing `return ...` and before the `# FAIL path: DEFER the donation.` comment:

```python
    # needs_review: the verdict is FAIL, but unjudged (ambiguous) proofs on days
    # not already counted could lift `valid` to target if they re-judge to passed.
    # valid_passed < target <= valid_passed + ambiguous_distinct_days. Park the
    # pact: NO donation, NO dispute window, stake stays committed. A later settle
    # (after the ambiguous proofs are re-judged) flows through normally because
    # needs_review is not terminal and not handled here.
    passed_days = {p.day_bucket for p in proofs if p.status == ProofStatus.passed}
    ambiguous_distinct_days = len(
        {
            p.day_bucket
            for p in proofs
            if p.status == ProofStatus.ambiguous and p.day_bucket not in passed_days
        }
    )
    if valid < pact.target_count <= valid + ambiguous_distinct_days:
        pact.status = PactStatus.needs_review
        pact.verdict_at = now
        # No payment, no spend_request_id, no dispute_window_closes_at.
        return pact, _build_verdict(
            pact, proofs, valid, PactStatus.needs_review, PaymentAction.none, None
        )
```

Note: `_build_verdict` only special-cases `PactStatus.succeeded` for its summary string; any other status (including `needs_review`) takes the generic "... Pact failed." summary, which is acceptable for this pause state. The `Verdict.status` field is `PactStatus`, so `needs_review` is a valid value and no model change is needed.

- [ ] **Step 5: Run the test — expect PASS**

```
uv run pytest tests/test_needs_review.py -v
```

Expected PASS: all five tests green — resolver error yields an ambiguous proof with the exact reason; target-4 (3 passed + 1 ambiguous) parks in `needs_review` with zero donation calls and no window; target-5 stays a clean FAIL that still donates after the window; re-settle after re-judge to passed succeeds.

- [ ] **Step 6: Run the full suite — expect no regressions**

```
uv run pytest tests/test_lifecycle_settle.py tests/test_lifecycle_proof.py tests/test_dispute_window.py -v
```

Expected PASS: the existing settle/proof/dispute tests are unchanged. SUCCESS and clean-FAIL paths are untouched (the needs_review branch only fires when `valid < target <= valid + ambiguous_distinct_days`, and those tests use only passed/failed proofs, so `ambiguous_distinct_days == 0` and the inequality can never hold). Then run the whole suite to confirm the global count holds:

```
uv run pytest -q
```

Expected: the prior 317 pass, plus the 5 new tests in `tests/test_needs_review.py`.

- [ ] **Step 7: Commit**

```
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' add src/pact/lifecycle.py tests/test_needs_review.py
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' commit -m "$(cat <<'EOF'
feat(lifecycle): needs_review on resolver error + ambiguous-decisive settle

submit_proof now guards provider.resolve: a raising resolver records the
Proof as ambiguous with judge_reason "judging unavailable (resolver error)"
instead of crashing the request.

settle adds a needs_review trigger: when the verdict is FAIL but ambiguous
proofs on un-counted days could flip it (valid < target <= valid +
ambiguous_distinct_days), the pact is parked in needs_review with no
donation and no dispute window; a later re-settle after re-judge proceeds
normally. SUCCESS and clean-FAIL behavior unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

**Call sites / signatures:** none changed. `submit_proof` and `settle` keep their exact existing signatures; the resolver guard and needs_review branch are internal. `PactStatus.needs_review` and the `evaluating -> needs_review` / `needs_review -> {succeeded, failed, evaluating}` transitions already exist in `ALLOWED_TRANSITIONS`, and `needs_review` is correctly absent from `_TERMINAL_STATUSES`, so the idempotent re-settle works with no further wiring.


### Task 5: Consent acknowledgment on confirm + write-lock

This task does two independent-but-related things: (a) make a pact refuse to start without an honest `consent_acknowledged=True` (ValueError in `confirm_and_start` -> 422 at the API), and (b) put a `threading.Lock` around every `Repository` write so concurrent FastAPI threadpool writes against the one shared SQLite connection can't corrupt it (this kills the demo Seed/Reset 500 race). Light honest acknowledgment, NOT a compliance gate.

**Files:**
- Modify: `/Users/chadd_mini/hermes-projects/pact/src/pact/lifecycle.py` (`confirm_and_start` gains `consent_acknowledged: bool = False`, raises `ValueError` if not acknowledged)
- Modify: `/Users/chadd_mini/hermes-projects/pact/src/pact/api.py` (`ConfirmIn` gains `consent_acknowledged: bool = False`; pass it into `confirm_and_start`)
- Modify: `/Users/chadd_mini/hermes-projects/pact/src/pact/repository.py` (add `threading.Lock`; guard every write method + schema writes)
- Modify (call sites — pass `consent_acknowledged=True`): `/Users/chadd_mini/hermes-projects/pact/tests/test_lifecycle_proof.py` (7 `confirm_and_start(...)` calls), `/Users/chadd_mini/hermes-projects/pact/tests/test_api_flow.py`, `/Users/chadd_mini/hermes-projects/pact/tests/test_api_day2.py`, `/Users/chadd_mini/hermes-projects/pact/tests/test_followups.py` (3 `POST /api/pacts` bodies)
- Test: `/Users/chadd_mini/hermes-projects/pact/tests/test_consent_and_lock.py` (new)

> Signature-change note. The existing `confirm_and_start(pact, stake_amount_cents, charity_id, clock, settings)` is called positionally in `tests/test_lifecycle_proof.py` (lines 67, 84, 94, 104, 122, 155, 181). We add `consent_acknowledged: bool = False` as the **last** parameter, so positional callers still bind correctly — but those tests will now hit the `not consent_acknowledged` guard and must pass `consent_acknowledged=True`. The HTTP call sites (`tests/test_api_flow.py:38`, `tests/test_api_day2.py:38`, `tests/test_followups.py:148`) send a JSON body and must add `"consent_acknowledged": True`. `demo.py` builds pacts directly via `_make_pact` (no `confirm_and_start`, no `POST /api/pacts`) so it is unaffected. The 422-on-missing-consent behavior is exercised by the NEW test below; the updated existing call sites keep the 317 suite green.

---

- [ ] **Step 1: Write the failing test**

Create `/Users/chadd_mini/hermes-projects/pact/tests/test_consent_and_lock.py`:

```python
from __future__ import annotations

import os
import tempfile
import threading
from datetime import datetime, timezone

import httpx
import pytest

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock
from pact.config import Settings
from pact.lifecycle import confirm_and_start, draft_pact
from pact.models import CoachingMessage, Pact, PactStatus, Rubric, StakeState
from pact.models import Modality
from pact.payment import TestLinkProvider
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def _clock() -> FixedClock:
    return FixedClock(datetime(2026, 6, 24, 18, 0, 0, tzinfo=timezone.utc))


def _settings(tmp_path) -> Settings:
    return Settings(db_path=str(tmp_path / "pact.db"))


def _build(tmp_path):
    clock = _clock()
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    provider = TestLLMProvider()
    payment = TestLinkProvider()
    tokens = TokenStore(ttl_minutes=10)
    settings = _settings(tmp_path)
    app = create_app(repo, provider, payment, tokens, clock, settings)
    return app, repo, clock, settings, provider


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# ── (a) lifecycle-level consent guard ───────────────────────────────────────


def test_confirm_and_start_requires_consent():
    clock = _clock()
    settings = Settings()
    provider = TestLLMProvider()
    pact = draft_pact("work out 5x this week or $20 to charity", provider, clock, settings)

    # No acknowledgment (default False) -> refuse to start.
    with pytest.raises(ValueError):
        confirm_and_start(pact, 1000, "world_central_kitchen", clock, settings)

    # Explicit False -> still refused.
    with pytest.raises(ValueError):
        confirm_and_start(
            pact, 1000, "world_central_kitchen", clock, settings,
            consent_acknowledged=False,
        )


def test_confirm_and_start_with_consent_activates():
    clock = _clock()
    settings = Settings()
    provider = TestLLMProvider()
    pact = draft_pact("work out 5x this week or $20 to charity", provider, clock, settings)

    started = confirm_and_start(
        pact, 1000, "world_central_kitchen", clock, settings,
        consent_acknowledged=True,
    )
    assert started.status == PactStatus.active
    assert started.stake_state == StakeState.committed
    assert started.stake_amount_cents == 1000


# ── (a) API-level consent guard ─────────────────────────────────────────────


@pytest.mark.anyio
async def test_api_confirm_without_consent_is_422(tmp_path):
    app, repo, clock, settings, provider = _build(tmp_path)
    async with _client(app) as client:
        r = await client.post(
            "/api/pacts/draft",
            json={"prompt": "work out 5x this week or $20 to charity"},
        )
        assert r.status_code == 200, r.text
        pact_id = r.json()["id"]

        # consent omitted -> default False -> 422
        r = await client.post(
            "/api/pacts",
            json={
                "pact_id": pact_id,
                "stake_amount_cents": 1500,
                "charity_id": "world_central_kitchen",
            },
        )
        assert r.status_code == 422, r.text

        # still draft — nothing started
        r = await client.get(f"/api/pacts/{pact_id}")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "draft"


@pytest.mark.anyio
async def test_api_confirm_with_consent_activates(tmp_path):
    app, repo, clock, settings, provider = _build(tmp_path)
    async with _client(app) as client:
        r = await client.post(
            "/api/pacts/draft",
            json={"prompt": "work out 5x this week or $20 to charity"},
        )
        assert r.status_code == 200, r.text
        pact_id = r.json()["id"]

        r = await client.post(
            "/api/pacts",
            json={
                "pact_id": pact_id,
                "stake_amount_cents": 1500,
                "charity_id": "world_central_kitchen",
                "consent_acknowledged": True,
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "active"
        assert r.json()["stake_amount_cents"] == 1500


# ── (b) repository write-lock under concurrency ─────────────────────────────


def _pact(idx: int) -> Pact:
    now = datetime(2026, 6, 24, 18, 0, 0, tzinfo=timezone.utc)
    return Pact(
        id=f"pact-conc-{idx}",
        owner="owner@example.com",
        original_prompt="x",
        title=f"Pact {idx}",
        goal="g",
        timezone="America/Los_Angeles",
        deadline_at=now,
        target_count=5,
        recommended_stake_cents=500,
        stake_amount_cents=500,
        charity_id="world_central_kitchen",
        charity_url="https://wck.org/donate",
        rubric=Rubric(
            modality=Modality.photo,
            require_token=True,
            must_show=["evidence"],
            reject_if=["stock"],
            min_distinct_days=5,
            count_target=5,
        ),
        status=PactStatus.active,
        stake_state=StakeState.committed,
        created_at=now,
        started_at=now,
    )


def test_repository_has_write_lock():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        repo = Repository.connect(path)
        # A guard lock must exist on the repository instance.
        assert isinstance(repo._write_lock, type(threading.Lock()))
    finally:
        os.remove(path)


def test_concurrent_writes_do_not_corrupt():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        repo = Repository.connect(path)
        repo.init_schema()

        errors: list[BaseException] = []
        n = 40

        def worker(i: int) -> None:
            try:
                repo.save_pact(_pact(i))
                msg = CoachingMessage(
                    id=f"cm-conc-{i}",
                    pact_id=f"pact-conc-{i}",
                    direction="outbound",
                    kind="mid_week",
                    body="keep going",
                    sent_at=datetime(2026, 6, 24, 18, 0, 0, tzinfo=timezone.utc),
                )
                repo.save_coaching_message(msg)
            except BaseException as exc:  # noqa: BLE001 - capture for assertion
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"concurrent writes raised: {errors!r}"
        # Every row landed: no lost/half-written writes.
        assert len(repo.list_pacts()) == n
        for i in range(n):
            assert repo.get_pact(f"pact-conc-{i}") is not None
            assert repo.get_coaching_message(f"cm-conc-{i}") is not None
    finally:
        os.remove(path)
```

> The `@pytest.mark.anyio` markers match the existing async HTTP tests (asyncio_mode=auto). If `CoachingMessage` requires different field names than `direction`/`kind`/`body`, Step 1's run will surface it (ImportError/validation); align the kwargs with `src/pact/models.py` before Step 3 — do not invent fields.

- [ ] **Step 2: Run the new test — expect FAIL**

```bash
uv run pytest tests/test_consent_and_lock.py -v
```

Expected: FAIL. `test_confirm_and_start_requires_consent` fails (no consent guard yet — `confirm_and_start` activates regardless and raises no `ValueError`; also `consent_acknowledged=` is an unexpected keyword -> `TypeError`). `test_api_confirm_without_consent_is_422` fails (returns 200, not 422). `test_repository_has_write_lock` fails (`AttributeError: 'Repository' object has no attribute '_write_lock'`). The `*_with_consent_*` and concurrency tests may also error on the unknown `consent_acknowledged` kwarg / missing attribute.

- [ ] **Step 3: Minimal implementation — consent guard in `confirm_and_start`**

In `/Users/chadd_mini/hermes-projects/pact/src/pact/lifecycle.py`, change the `confirm_and_start` signature and add the guard as the first check. Replace:

```python
def confirm_and_start(
    pact: Pact,
    stake_amount_cents: int,
    charity_id: str,
    clock: Clock,
    settings: Settings,
) -> Pact:
    if not (settings.min_stake_cents <= stake_amount_cents <= settings.max_stake_cents):
```

with:

```python
def confirm_and_start(
    pact: Pact,
    stake_amount_cents: int,
    charity_id: str,
    clock: Clock,
    settings: Settings,
    consent_acknowledged: bool = False,
) -> Pact:
    # Honest acknowledgment, not a compliance gate: a pact cannot start until the
    # owner explicitly acknowledges that real money goes to charity on failure.
    if not consent_acknowledged:
        raise ValueError(
            "consent_acknowledged must be True to start a pact "
            "(money goes to charity on failure)"
        )
    if not (settings.min_stake_cents <= stake_amount_cents <= settings.max_stake_cents):
```

- [ ] **Step 4: Minimal implementation — `ConfirmIn` + API wiring**

In `/Users/chadd_mini/hermes-projects/pact/src/pact/api.py`, extend `ConfirmIn`. Replace:

```python
class ConfirmIn(BaseModel):
    pact_id: str
    stake_amount_cents: int
    charity_id: str
```

with:

```python
class ConfirmIn(BaseModel):
    pact_id: str
    stake_amount_cents: int
    charity_id: str
    consent_acknowledged: bool = False
```

Then pass it through the confirm route. Replace:

```python
            pact = confirm_and_start(
                pact, body.stake_amount_cents, body.charity_id, clock, settings
            )
```

with:

```python
            pact = confirm_and_start(
                pact,
                body.stake_amount_cents,
                body.charity_id,
                clock,
                settings,
                consent_acknowledged=body.consent_acknowledged,
            )
```

The existing `except (ValueError, TransitionError)` handler already maps the new `ValueError` to HTTP 422 — no other change needed.

- [ ] **Step 5: Minimal implementation — repository write-lock**

In `/Users/chadd_mini/hermes-projects/pact/src/pact/repository.py`, add the import and a lock instance, then guard every write. Replace the import block + `__init__`:

```python
from __future__ import annotations

import sqlite3
from datetime import datetime

from pact.models import (
    CoachingMessage,
    Pact,
    PactStatus,
    Profile,
    Proof,
    ReasoningTask,
    Verdict,
)


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
```

with:

```python
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime

from pact.models import (
    CoachingMessage,
    Pact,
    PactStatus,
    Profile,
    Proof,
    ReasoningTask,
    Verdict,
)


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        # One shared sqlite3 connection (check_same_thread=False) is written from
        # FastAPI's threadpool. SQLite serializes statements but interleaved
        # execute+commit from two threads can still corrupt/race; a process-local
        # lock makes each write method atomic. Reads stay lock-free.
        self._write_lock = threading.Lock()
```

Now wrap every write body. `init_schema` — wrap the whole method body in the lock. Replace:

```python
    def init_schema(self) -> None:
        self.conn.executescript(
```

with:

```python
    def init_schema(self) -> None:
        with self._write_lock:
            self._init_schema_locked()

    def _init_schema_locked(self) -> None:
        self.conn.executescript(
```

(The existing body of `init_schema` — the `executescript`, the `PRAGMA`/`ALTER` migration, and the final `self.conn.commit()` — stays exactly as-is, now living inside `_init_schema_locked`, indentation unchanged since it's still a method.)

`save_pact` — wrap the execute+commit. Replace:

```python
    def save_pact(self, pact: Pact) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO pacts (id, owner, status, deadline_at, data)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                pact.id,
                pact.owner,
                pact.status.value,
                pact.deadline_at.isoformat(),
                pact.model_dump_json(),
            ),
        )
        self.conn.commit()
```

with:

```python
    def save_pact(self, pact: Pact) -> None:
        with self._write_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO pacts (id, owner, status, deadline_at, data)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    pact.id,
                    pact.owner,
                    pact.status.value,
                    pact.deadline_at.isoformat(),
                    pact.model_dump_json(),
                ),
            )
            self.conn.commit()
```

`save_proof` — replace:

```python
    def save_proof(self, proof: Proof) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO proofs (id, pact_id, data)
            VALUES (?, ?, ?)
            """,
            (proof.id, proof.pact_id, proof.model_dump_json()),
        )
        self.conn.commit()
```

with:

```python
    def save_proof(self, proof: Proof) -> None:
        with self._write_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO proofs (id, pact_id, data)
                VALUES (?, ?, ?)
                """,
                (proof.id, proof.pact_id, proof.model_dump_json()),
            )
            self.conn.commit()
```

`save_task` — replace:

```python
    def save_task(self, task: ReasoningTask) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO tasks (id, pact_id, status, required_capability, data)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                task.id,
                task.pact_id,
                task.status.value,
                task.required_capability,
                task.model_dump_json(),
            ),
        )
        self.conn.commit()
```

with:

```python
    def save_task(self, task: ReasoningTask) -> None:
        with self._write_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO tasks (id, pact_id, status, required_capability, data)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.pact_id,
                    task.status.value,
                    task.required_capability,
                    task.model_dump_json(),
                ),
            )
            self.conn.commit()
```

`save_verdict` — replace:

```python
    def save_verdict(self, verdict: Verdict) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO verdicts (pact_id, status, data)
            VALUES (?, ?, ?)
            """,
            (verdict.pact_id, verdict.status.value, verdict.model_dump_json()),
        )
        self.conn.commit()
```

with:

```python
    def save_verdict(self, verdict: Verdict) -> None:
        with self._write_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO verdicts (pact_id, status, data)
                VALUES (?, ?, ?)
                """,
                (verdict.pact_id, verdict.status.value, verdict.model_dump_json()),
            )
            self.conn.commit()
```

`save_profile` — replace:

```python
    def save_profile(self, profile: Profile) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO profiles (owner, data)
            VALUES (?, ?)
            """,
            (profile.owner, profile.model_dump_json()),
        )
        self.conn.commit()
```

with:

```python
    def save_profile(self, profile: Profile) -> None:
        with self._write_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO profiles (owner, data)
                VALUES (?, ?)
                """,
                (profile.owner, profile.model_dump_json()),
            )
            self.conn.commit()
```

`save_coaching_message` — replace:

```python
    def save_coaching_message(self, msg: CoachingMessage) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO coaching_messages (id, pact_id, sent_at, delivered_at, data)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                msg.id,
                msg.pact_id,
                msg.sent_at.isoformat(),
                msg.delivered_at.isoformat() if msg.delivered_at is not None else None,
                msg.model_dump_json(),
            ),
        )
        self.conn.commit()
```

with:

```python
    def save_coaching_message(self, msg: CoachingMessage) -> None:
        with self._write_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO coaching_messages (id, pact_id, sent_at, delivered_at, data)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    msg.id,
                    msg.pact_id,
                    msg.sent_at.isoformat(),
                    msg.delivered_at.isoformat() if msg.delivered_at is not None else None,
                    msg.model_dump_json(),
                ),
            )
            self.conn.commit()
```

`reset_all` — replace:

```python
    def reset_all(self) -> None:
        self.conn.executescript(
            """
            DELETE FROM pacts;
            DELETE FROM proofs;
            DELETE FROM tasks;
            DELETE FROM verdicts;
            DELETE FROM profiles;
            DELETE FROM coaching_messages;
            """
        )
        self.conn.commit()
```

with:

```python
    def reset_all(self) -> None:
        with self._write_lock:
            self.conn.executescript(
                """
                DELETE FROM pacts;
                DELETE FROM proofs;
                DELETE FROM tasks;
                DELETE FROM verdicts;
                DELETE FROM profiles;
                DELETE FROM coaching_messages;
                """
            )
            self.conn.commit()
```

> `update_pact` and `update_task` delegate to `save_pact`/`save_task`, so they inherit the lock — leave them as one-line delegators (do NOT add a second `with self._write_lock:`, that would self-deadlock on a non-reentrant `Lock`). All read methods (`get_*`, `list_*`, `due_active_pacts`, `pending_tasks`, `outbox`) stay lock-free per the contract.

- [ ] **Step 6: Update existing call sites — pass `consent_acknowledged=True`**

In `/Users/chadd_mini/hermes-projects/pact/tests/test_lifecycle_proof.py`, the 7 positional `confirm_and_start(...)` calls now hit the consent guard. Update each to pass `consent_acknowledged=True`.

Line 67 — replace:
```python
    started = confirm_and_start(pact, 1000, "world_central_kitchen", clock, settings)
```
with:
```python
    started = confirm_and_start(
        pact, 1000, "world_central_kitchen", clock, settings, consent_acknowledged=True
    )
```

Line 84 (inside `pytest.raises(ValueError)` for stake-above-cap) — replace:
```python
        confirm_and_start(pact, settings.max_stake_cents + 1, "world_central_kitchen", clock, settings)
```
with:
```python
        confirm_and_start(
            pact, settings.max_stake_cents + 1, "world_central_kitchen", clock, settings,
            consent_acknowledged=True,
        )
```

Line 94 (stake-below-cap) — replace:
```python
        confirm_and_start(pact, settings.min_stake_cents - 1, "world_central_kitchen", clock, settings)
```
with:
```python
        confirm_and_start(
            pact, settings.min_stake_cents - 1, "world_central_kitchen", clock, settings,
            consent_acknowledged=True,
        )
```

Line 104 (unknown-charity) — replace:
```python
        confirm_and_start(pact, 1000, "not_a_real_charity", clock, settings)
```
with:
```python
        confirm_and_start(
            pact, 1000, "not_a_real_charity", clock, settings, consent_acknowledged=True
        )
```

> Lines 84/94/104 still raise `ValueError` for their original reason (stake caps / unknown charity); passing `consent_acknowledged=True` ensures the guard isn't the thing that raises, so each test still asserts the behavior it intends.

The 3 multiline calls at lines 122, 155, 181 share the identical text:
```python
    pact = confirm_and_start(
        _draft(clock, settings, provider), 1000, "world_central_kitchen", clock, settings
    )
```
Replace all 3 (use `replace_all`) with:
```python
    pact = confirm_and_start(
        _draft(clock, settings, provider), 1000, "world_central_kitchen", clock, settings,
        consent_acknowledged=True,
    )
```

In `/Users/chadd_mini/hermes-projects/pact/tests/test_api_flow.py` (line ~38), `/Users/chadd_mini/hermes-projects/pact/tests/test_api_day2.py` (line ~38), and `/Users/chadd_mini/hermes-projects/pact/tests/test_followups.py` (line ~148), each has a `POST /api/pacts` body. Replace this exact JSON block in each file:
```python
        json={
            "pact_id": pact_id,
            "stake_amount_cents": 1500,
            "charity_id": "world_central_kitchen",
        },
```
with:
```python
        json={
            "pact_id": pact_id,
            "stake_amount_cents": 1500,
            "charity_id": "world_central_kitchen",
            "consent_acknowledged": True,
        },
```

> `test_followups.py` is indented one extra level (the body lives inside a nested block — note its `"/api/pacts",` is at deeper indentation than the others). Match that file's exact existing indentation when editing; if the literal above doesn't match, read the surrounding lines and add `"consent_acknowledged": True,` as the final key inside that same `json={...}`.

- [ ] **Step 7: Run the new test + the touched suites — expect PASS**

```bash
uv run pytest tests/test_consent_and_lock.py tests/test_lifecycle_proof.py tests/test_api_flow.py tests/test_api_day2.py tests/test_followups.py -v
```

Expected: PASS. The new file's 6 tests pass (consent required -> ValueError/422; consent given -> active; `_write_lock` present; 40 concurrent writers raise nothing and all 80 rows land), and every updated call site keeps its original assertions green.

- [ ] **Step 8: Run the full suite — expect PASS (no regressions)**

```bash
uv run pytest -q
```

Expected: the full suite passes (was 317; now 317 + the 6 new tests in `test_consent_and_lock.py` = 323). If anything else POSTs `/api/pacts` or calls `confirm_and_start` without consent, the failure names the file — add `consent_acknowledged=True` there the same way and re-run.

- [ ] **Step 9: Commit**

```bash
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' add \
  src/pact/lifecycle.py src/pact/api.py src/pact/repository.py \
  tests/test_consent_and_lock.py tests/test_lifecycle_proof.py \
  tests/test_api_flow.py tests/test_api_day2.py tests/test_followups.py

git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' commit -m "$(cat <<'EOF'
feat(pact): require consent on confirm + lock repository writes

confirm_and_start gains consent_acknowledged (ValueError -> API 422) so a
pact cannot start without an honest acknowledgment that money goes to
charity on failure. Repository wraps every write method in a threading.Lock,
making writes against the single shared SQLite connection atomic and killing
the demo Seed/Reset 500 race; reads stay lock-free.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```


### Task 6: One-process serve: FastAPI serves the built SPA

**Files:**
- Modify: `/Users/chadd_mini/hermes-projects/pact/src/pact/main.py`
- Test: `/Users/chadd_mini/hermes-projects/pact/tests/test_serve_spa.py` (Create)

**Context (verified against source):**
- `build_app(env=None)` lives in `src/pact/main.py`; the repo root (where `web/dist` sits) is `Path(__file__).resolve().parents[2]` (`src/pact/main.py` → `parents[0]=src/pact`, `parents[1]=src`, `parents[2]=repo root`).
- `create_app(...)` in `api.py` registers only `/api/*` and `/demo/*` routes and returns the `FastAPI`. Per the contract we do NOT change `create_app`'s mounting behavior — the SPA mount happens in `build_app` after `create_app` returns, so all existing tests that call `create_app` directly stay green. We add the mount in `build_app` only.
- The built SPA references absolute asset URLs `/assets/index-*.js` and `/assets/index-*.css` (confirmed in `web/dist/index.html`), so static assets must be served under `/assets`.
- Mount order matters: the SPA catch-all must be registered LAST and must explicitly NOT shadow `/api` or `/demo`. `StaticFiles` for `/assets` is registered before the catch-all. `fastapi.staticfiles.StaticFiles` and `fastapi.responses.FileResponse` are importable (verified).
- The lifespan is attached via `app.router.lifespan_context = lifespan` (existing); mounting must happen on the same `app` object, before returning.

**TDD checkbox steps:**

- [ ] **Step 1: Write the failing test**

Create `/Users/chadd_mini/hermes-projects/pact/tests/test_serve_spa.py`:

```python
import os
import tempfile
from pathlib import Path

import httpx
import pytest


def _make_dist(root: Path) -> Path:
    """Create a minimal web/dist with index.html + one asset under root."""
    dist = root / "web" / "dist"
    (dist / "assets").mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><head>"
        '<script type="module" src="/assets/app.js"></script>'
        "</head><body><div id=\"root\">PACT_SPA_MARKER</div></body></html>",
        encoding="utf-8",
    )
    (dist / "assets" / "app.js").write_text(
        "console.log('PACT_ASSET_MARKER');", encoding="utf-8"
    )
    return dist


def _env_for_db() -> tuple[str, dict]:
    """A throwaway sqlite db path + a demo-mode env (no real-time ticker)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    env = {
        "PACT_DB_PATH": path,
        "PACT_CLOCK_MODE": "demo",
        "PACT_DEMO_SEED_ISO": "2026-06-24T12:00:00+00:00",
    }
    return path, env


async def test_serves_index_at_root_when_dist_present(monkeypatch, tmp_path):
    """With a web/dist present, GET / returns index.html (the SPA shell)."""
    import pact.main as main

    dist = _make_dist(tmp_path)
    # Point build_app's dist resolution at our tmp dist via the helper it uses.
    monkeypatch.setattr(main, "_dist_dir", lambda settings=None: dist)

    path, env = _env_for_db()
    try:
        app = main.build_app(env=env)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.get("/")
            assert resp.status_code == 200
            assert "PACT_SPA_MARKER" in resp.text
            assert "text/html" in resp.headers["content-type"]
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


async def test_serves_static_asset_when_dist_present(monkeypatch, tmp_path):
    """Built JS/CSS assets are served from /assets/* so the SPA actually boots."""
    import pact.main as main

    dist = _make_dist(tmp_path)
    monkeypatch.setattr(main, "_dist_dir", lambda settings=None: dist)

    path, env = _env_for_db()
    try:
        app = main.build_app(env=env)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.get("/assets/app.js")
            assert resp.status_code == 200
            assert "PACT_ASSET_MARKER" in resp.text
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


async def test_unknown_non_api_path_falls_back_to_index(monkeypatch, tmp_path):
    """A client-side route (deep link) returns index.html so the SPA can route it."""
    import pact.main as main

    dist = _make_dist(tmp_path)
    monkeypatch.setattr(main, "_dist_dir", lambda settings=None: dist)

    path, env = _env_for_db()
    try:
        app = main.build_app(env=env)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.get("/pact/some-client-route")
            assert resp.status_code == 200
            assert "PACT_SPA_MARKER" in resp.text
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


async def test_api_routes_not_shadowed_by_spa(monkeypatch, tmp_path):
    """Mounting the SPA must NOT shadow /api: a real API route still answers."""
    import pact.main as main

    dist = _make_dist(tmp_path)
    monkeypatch.setattr(main, "_dist_dir", lambda settings=None: dist)

    path, env = _env_for_db()
    try:
        app = main.build_app(env=env)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            # /api/charities is a real GET route from create_app.
            resp = await client.get("/api/charities")
            assert resp.status_code == 200
            body = resp.json()
            assert isinstance(body, list)
            assert "PACT_SPA_MARKER" not in resp.text
            # An UNKNOWN /api path must NOT fall back to index.html — it 404s as JSON.
            missing = await client.get("/api/does-not-exist")
            assert missing.status_code == 404
            assert "PACT_SPA_MARKER" not in missing.text
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


async def test_demo_routes_not_shadowed_by_spa(monkeypatch, tmp_path):
    """Mounting the SPA must NOT shadow /demo: POST /demo/seed still works."""
    import pact.main as main

    dist = _make_dist(tmp_path)
    monkeypatch.setattr(main, "_dist_dir", lambda settings=None: dist)

    path, env = _env_for_db()
    try:
        app = main.build_app(env=env)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post("/demo/seed")
            assert resp.status_code == 200
            assert "PACT_SPA_MARKER" not in resp.text
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


async def test_friendly_note_when_dist_absent(monkeypatch, tmp_path):
    """With NO web/dist, GET / returns a friendly 200 note instead of crashing."""
    import pact.main as main

    missing_dist = tmp_path / "web" / "dist"  # never created
    monkeypatch.setattr(main, "_dist_dir", lambda settings=None: missing_dist)

    path, env = _env_for_db()
    try:
        app = main.build_app(env=env)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.get("/")
            assert resp.status_code == 200
            assert "npm run build" in resp.text
            # /api still works even without a built SPA.
            api = await client.get("/api/charities")
            assert api.status_code == 200
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
```

- [ ] **Step 2: Run the test — expect FAIL**

```
uv run pytest tests/test_serve_spa.py -v
```

Expected: FAIL. `build_app` does not yet expose `_dist_dir` (so `monkeypatch.setattr(main, "_dist_dir", ...)` raises `AttributeError`) and does not mount the SPA, so `GET /` 404s and the friendly-note assertion fails.

- [ ] **Step 3: Minimal implementation**

Replace the entire contents of `/Users/chadd_mini/hermes-projects/pact/src/pact/main.py` with:

```python
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Mapping

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from pact.anticheat import TokenStore
from pact.api import create_app
from pact.clock import FixedClock, RealClock
from pact.config import Settings, load_settings
from pact.factory import build_payment_provider, build_reasoning_provider
from pact.lifecycle import reconcile_on_startup
from pact.repository import Repository
from pact.scheduler import run_ticker_loop

# Paths the SPA catch-all must NEVER serve index.html for; these belong to the
# API/demo surface registered by create_app and must keep their own 404s.
_RESERVED_PREFIXES = ("/api", "/demo")

_FRIENDLY_NOTE = (
    "<!doctype html><html><head><title>Pact</title></head><body>"
    "<h1>Pact</h1>"
    "<p>The web UI has not been built yet. Run "
    "<code>npm install && npm run build</code> in <code>web/</code> "
    "to produce <code>web/dist</code>, then reload.</p>"
    "<p>The JSON API is live at <code>/api</code>.</p>"
    "</body></html>"
)


def _dist_dir(settings: Settings | None = None) -> Path:
    """Resolve the built SPA directory (web/dist) relative to the repo root.

    src/pact/main.py -> parents[2] is the repo root that holds web/dist.
    Tests monkeypatch this helper to point at a throwaway dist.
    """
    return Path(__file__).resolve().parents[2] / "web" / "dist"


def _mount_spa(app: FastAPI, settings: Settings) -> None:
    """If web/dist exists, serve it from this same process: static assets + an
    SPA fallback at GET / and for unknown non-API/non-demo paths. If absent,
    GET / returns a friendly build note. Never shadows /api or /demo.
    """
    dist = _dist_dir(settings)
    index = dist / "index.html"
    assets = dist / "assets"

    if not index.is_file():
        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def _missing_dist() -> HTMLResponse:
            return HTMLResponse(_FRIENDLY_NOTE)

        return

    # Real built assets (e.g. /assets/index-*.js, /assets/index-*.css).
    if assets.is_dir():
        app.mount(
            "/assets", StaticFiles(directory=str(assets)), name="assets"
        )

    @app.get("/", include_in_schema=False)
    def _spa_root() -> FileResponse:
        return FileResponse(str(index))

    # SPA fallback: any other GET that is NOT an API/demo path returns the shell
    # so client-side routing (deep links) works. Registered LAST so concrete
    # /api and /demo routes win; we still guard explicitly for safety.
    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa_fallback(full_path: str) -> FileResponse:
        from fastapi import HTTPException

        if ("/" + full_path).startswith(_RESERVED_PREFIXES):
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(str(index))


def build_app(env: Mapping[str, str] | None = None):
    # Read configuration from the process environment so PACT_CLOCK_MODE=demo (and the
    # other PACT_* knobs) take effect at startup. Tests inject a dict instead of os.environ.
    settings = load_settings(os.environ if env is None else env)
    repo = Repository.connect(settings.db_path)
    repo.init_schema()
    if settings.clock_mode == "demo":
        clock = FixedClock(datetime.fromisoformat(settings.demo_seed_iso))
    else:
        clock = RealClock()
    # Config-driven provider/payment selection (locked: the brain is a Hermes AGENT;
    # TestLLMProvider is only the deterministic fallback/stub). build_reasoning_provider
    # returns the stub directly in stub/test_llm mode and a BrokerReasoningProvider
    # (which enqueues for a connected agent + falls back) in hybrid/agent_only mode.
    provider = build_reasoning_provider(settings, repo, clock)
    payment = build_payment_provider(settings)
    tokens = TokenStore()

    @asynccontextmanager
    async def lifespan(app):
        # Startup: one reconciliation sweep so a server restarted mid-pact settles
        # any active pact past its deadline and closes any elapsed dispute window.
        reconcile_on_startup(repo, clock, payment, settings)

        # Autonomous ticker: only on a real-time clock with the scheduler enabled.
        # In demo mode (FixedClock) time is driven by /demo/advance-day, so the
        # real-time ticker must NOT run.
        app.state.ticker_task = None
        app.state.ticker_stop = None
        if settings.scheduler_enabled and isinstance(clock, RealClock):
            stop = asyncio.Event()
            app.state.ticker_stop = stop
            app.state.ticker_task = asyncio.create_task(
                run_ticker_loop(repo, clock, payment, settings, stop=stop)
            )
        try:
            yield
        finally:
            # Shutdown: signal stop and cancel the background ticker if running.
            if app.state.ticker_stop is not None:
                app.state.ticker_stop.set()
            task = app.state.ticker_task
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = create_app(repo, provider, payment, tokens, clock, settings)
    # create_app's signature stays unchanged; we attach the lifespan to the built app.
    app.router.lifespan_context = lifespan
    # Local-first DX: one process serves both the JSON API and the built SPA.
    # Mounted AFTER the API/demo routes so the SPA catch-all never shadows them.
    _mount_spa(app, settings)
    return app


app = build_app()
```

- [ ] **Step 4: Run the test — expect PASS**

```
uv run pytest tests/test_serve_spa.py -v
```

Expected: PASS (all 7 tests green — index at `/`, asset at `/assets/app.js`, deep-link fallback, `/api` not shadowed + unknown `/api` 404s, `/demo/seed` not shadowed, friendly note when dist absent).

- [ ] **Step 5: Run the existing suites that touch main.py + the full suite — expect PASS**

```
uv run pytest tests/test_lifespan_scheduler.py tests/test_smoke.py -v
uv run pytest -q
```

Expected: PASS. `test_lifespan_scheduler.py` still passes (lifespan attach/ticker logic unchanged); the full suite stays at 317+ (the new file adds tests). `create_app` is untouched, so every test calling `create_app` directly is unaffected, and the real `web/dist` already on disk means the production `app = build_app()` mounts the SPA without error.

- [ ] **Step 6: Commit**

```
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' add src/pact/main.py tests/test_serve_spa.py
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' commit -m "$(printf 'feat(main): one-process serve — FastAPI serves built SPA\n\nMount web/dist static assets + SPA fallback in build_app so GET / and\nunknown non-API/non-demo paths return index.html; friendly build note\nwhen web/dist is absent. /api and /demo routes are never shadowed.\ncreate_app is unchanged.\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

**Signature/call-site notes:** No existing signature changes. `create_app(repo, provider, payment, tokens, clock, settings)` is untouched, so no call sites need updating; the SPA mount is added purely inside `build_app`. `_dist_dir(settings=None)` and `_mount_spa(app, settings)` are new module-level helpers in `main.py` (tests monkeypatch `pact.main._dist_dir`). The new module imports `Path`, `FileResponse`, `HTMLResponse`, `StaticFiles`, and `Settings` (all importable in the existing environment, verified).


### Task 7: Seed coaching activity + favicon + launcher

**Files:**
- Modify: `src/pact/demo.py` (add `_coaching_message` helper + emit 1–2 outbound rows on LIVE in `seed`)
- Create: `web/public/favicon.svg` (wax-seal/contract glyph)
- Modify: `web/index.html` (reference the favicon)
- Create: `scripts/dev.sh` (one-command build + serve launcher; executable)
- Test: `tests/test_demo_coaching_seed.py`

Context (verified against real source — use these exact signatures):
- `CoachingMessage` fields (`src/pact/models.py:169`): `id, pact_id, direction, trigger, pact_state_snapshot:dict={}, channel:str="web", body, sent_at, delivered_at:datetime|None=None`.
- `Repository.save_coaching_message(msg)`, `Repository.list_coaching_messages(pact_id) -> list[CoachingMessage]` (ordered by `sent_at`), `Repository.outbox(owner) -> list[CoachingMessage]` (returns only `direction == "outbound"` with `delivered_at is None`, ordered by `sent_at`).
- The seeded pact owner is `colehaddad40@gmail.com` (`_make_pact` in `demo.py:53`). `reset()` already calls `repo.reset_all()` then `seed()`, and `reset_all()` deletes `coaching_messages` — so reset clears + reseeds the new rows automatically with no extra code.
- Valid triggers already used in `coaching.py`: `mid_week`, `behind_pace` (`direction == "outbound"`).
- For deterministic stable ids, build the `CoachingMessage` directly in `demo.py` (do NOT call `coaching.generate_coach_message`, which would hit a provider). Hard-code ids `coach-live-mid_week` / `coach-live-behind_pace` so reseed overwrites in place.

---

- [ ] **Step 1: Write the failing test**

Create `tests/test_demo_coaching_seed.py`:

```python
from datetime import datetime, timezone

from pact.clock import FixedClock
from pact.config import load_settings
from pact.demo import reset, seed


def _clock() -> FixedClock:
    # Same pinned demo instant the other demo tests use.
    return FixedClock(datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc))


_OWNER = "colehaddad40@gmail.com"


def test_seed_creates_outbound_coaching_on_live(repo):
    clock = _clock()
    settings = load_settings({})

    ids = seed(repo, clock, settings)
    live_id = ids["live"]

    msgs = repo.list_coaching_messages(live_id)
    outbound = [m for m in msgs if m.direction == "outbound"]
    assert len(outbound) >= 1
    # All seeded coaching rows hang off the LIVE pact only.
    assert all(m.pact_id == live_id for m in outbound)
    # They carry real, recognized triggers and non-empty bodies.
    triggers = {m.trigger for m in outbound}
    assert triggers.issubset({"mid_week", "behind_pace"})
    assert "mid_week" in triggers
    for m in outbound:
        assert m.channel == "web"
        assert m.body.strip()
        assert m.delivered_at is None  # undelivered -> shows up in outbox


def test_seeded_coaching_is_visible_in_outbox(repo):
    clock = _clock()
    settings = load_settings({})

    seed(repo, clock, settings)

    out = repo.outbox(_OWNER)
    assert len(out) >= 1
    assert all(m.direction == "outbound" for m in out)
    assert all(m.delivered_at is None for m in out)


def test_coaching_ids_are_stable_across_seed(repo):
    settings = load_settings({})

    ids_a = seed(repo, _clock(), settings)
    msgs_a = repo.list_coaching_messages(ids_a["live"])
    ids_b = seed(repo, _clock(), settings)
    msgs_b = repo.list_coaching_messages(ids_b["live"])

    # Re-seeding overwrites in place (stable ids): no duplication.
    assert {m.id for m in msgs_a} == {m.id for m in msgs_b}
    assert len(msgs_a) == len(msgs_b)


def test_reset_clears_and_reseeds_coaching(repo):
    settings = load_settings({})

    seed(repo, _clock(), settings)
    ids = reset(repo, _clock(), settings)

    msgs = repo.list_coaching_messages(ids["live"])
    outbound = [m for m in msgs if m.direction == "outbound"]
    # Reset wiped coaching_messages then reseeded -> still exactly the seeded set.
    assert len(outbound) >= 1
    out = repo.outbox("colehaddad40@gmail.com")
    assert len(out) == len(outbound)
```

- [ ] **Step 2: Run the test — expect FAIL**

```bash
uv run pytest tests/test_demo_coaching_seed.py -v
```

Expected: FAIL. `test_seed_creates_outbound_coaching_on_live`, `test_seeded_coaching_is_visible_in_outbox`, and `test_reset_clears_and_reseeds_coaching` fail with `assert len(...) >= 1` (0) / `assert len(out) >= 1` (0) because `seed()` currently creates no coaching rows. `test_coaching_ids_are_stable_across_seed` passes vacuously (both empty) but the others prove the gap.

- [ ] **Step 3: Minimal implementation — emit coaching rows in `seed()`**

In `src/pact/demo.py`, add the `CoachingMessage` import to the existing `from pact.models import (...)` block. The current block is:

```python
from pact.models import (
    Modality,
    Pact,
    PactStatus,
    Proof,
    ProofStatus,
    Rubric,
    StakeState,
)
```

Replace it with (adds `CoachingMessage`):

```python
from pact.models import (
    CoachingMessage,
    Modality,
    Pact,
    PactStatus,
    Proof,
    ProofStatus,
    Rubric,
    StakeState,
)
```

Add this helper just below `_passed_proof` (before `def seed(`):

```python
def _coaching_message(
    msg_id: str,
    pact_id: str,
    trigger: str,
    body: str,
    sent_at: datetime,
    snapshot: dict,
) -> CoachingMessage:
    """An outbound, undelivered coach nudge with a stable id (repeatable reset)."""
    return CoachingMessage(
        id=msg_id,
        pact_id=pact_id,
        direction="outbound",
        trigger=trigger,
        pact_state_snapshot=snapshot,
        channel="web",
        body=body,
        sent_at=sent_at,
        delivered_at=None,
    )
```

In `seed()`, the LIVE block currently ends with:

```python
    repo.save_pact(live)
    for proof in live_proofs:
        repo.save_proof(proof)

    return {"win": win.id, "fail": fail.id, "live": live.id}
```

Replace it with (adds two outbound coaching rows on LIVE before the return):

```python
    repo.save_pact(live)
    for proof in live_proofs:
        repo.save_proof(proof)

    # Seed visible coaching activity on the LIVE pact so the coach pane and the
    # outbox are alive immediately after Seed. Outbound + undelivered so they
    # surface in repo.outbox(owner). Stable ids -> /demo/reset overwrites in place.
    live_snapshot = {"valid": 2, "target": live.target_count, "days_left": 4}
    coaching = [
        _coaching_message(
            "coach-live-mid_week",
            live.id,
            "mid_week",
            "Midway check-in: 2 of 5 days logged. Nice start — keep the streak going.",
            now - timedelta(days=1, hours=2),
            live_snapshot,
        ),
        _coaching_message(
            "coach-live-behind_pace",
            live.id,
            "behind_pace",
            "Heads up: you're a touch behind pace with 4 days left. One session today "
            "keeps $5 with you instead of World Central Kitchen.",
            now - timedelta(hours=2),
            live_snapshot,
        ),
    ]
    for msg in coaching:
        repo.save_coaching_message(msg)

    return {"win": win.id, "fail": fail.id, "live": live.id}
```

(`now` and `timedelta` are already in scope: `now = clock.now()` at the top of `seed()`, and `timedelta` is imported at the top of `demo.py`.)

- [ ] **Step 4: Run the test — expect PASS**

```bash
uv run pytest tests/test_demo_coaching_seed.py -v
```

Expected: 4 passed. Then run the existing demo suite to confirm no regression (the new rows live only on LIVE and reset already wipes `coaching_messages`):

```bash
uv run pytest tests/test_demo_seed.py tests/test_demo_advance_reset.py tests/test_api_demo.py -v
```

Expected: all pass.

- [ ] **Step 5: Add the favicon and reference it**

Create `web/public/favicon.svg` (a minimal wax-seal / contract glyph — circular seal with an embossed check, no external deps):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">
  <rect width="64" height="64" rx="12" fill="#1c1917"/>
  <circle cx="32" cy="32" r="20" fill="#b45309" stroke="#f59e0b" stroke-width="2"/>
  <circle cx="32" cy="32" r="13" fill="none" stroke="#fcd34d" stroke-width="1.5" stroke-dasharray="2 2"/>
  <path d="M24 33l5.5 6L41 26" fill="none" stroke="#fff7ed" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
```

In `web/index.html`, the `<head>` currently has the `<meta name="viewport" ...>` line followed by `<link rel="preconnect" ...>`. Add a favicon link right after the viewport meta. Change:

```html
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
```

to:

```html
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
```

(Vite copies `web/public/favicon.svg` to the dist root, so `/favicon.svg` resolves both in `vite dev` and in the single-process `uvicorn pact.main:app` serving `web/dist`.)

- [ ] **Step 6: Add the one-command launcher**

Create `scripts/dev.sh`:

```bash
#!/usr/bin/env bash
# Pact local-first launcher: build the SPA, then run ONE uvicorn process that
# serves the built app + API together in demo clock mode.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Building web app (web/ -> web/dist)"
( cd web && npm install && npm run build )

echo "==> Starting Pact (demo clock) on http://127.0.0.1:8000"
PACT_CLOCK_MODE=demo uv run uvicorn pact.main:app --host 127.0.0.1 --port 8000 "$@"
```

Make it executable:

```bash
chmod +x scripts/dev.sh
```

(No automated test drives the script — it does a real `npm`/`uvicorn` run, which is non-deterministic and out of scope for the test suite. Confirm it exists and is executable.)

- [ ] **Step 7: Verify launcher bits + full suite**

```bash
test -x scripts/dev.sh && echo "dev.sh is executable"
test -f web/public/favicon.svg && grep -q 'favicon.svg' web/index.html && echo "favicon wired"
uv run pytest tests/test_demo_coaching_seed.py tests/test_demo_seed.py tests/test_demo_advance_reset.py tests/test_api_demo.py -q
```

Expected: prints both confirmations and the demo tests pass.

- [ ] **Step 8: Commit**

```bash
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' add \
  src/pact/demo.py web/public/favicon.svg web/index.html scripts/dev.sh tests/test_demo_coaching_seed.py
git -c user.name='Cole Haddad' -c user.email='colehaddad40@gmail.com' commit -m "$(cat <<'EOF'
feat(demo): seed coaching activity + favicon + one-command launcher

demo.seed() now writes two outbound, undelivered CoachingMessage rows on the
LIVE pact (mid_week + behind_pace) with stable ids, so the coach pane and the
outbox are visibly alive right after Seed; reset_all() already clears them so
/demo/reset re-seeds cleanly. Adds web/public/favicon.svg (wax-seal glyph) wired
into web/index.html, and scripts/dev.sh to build the SPA then run a single
PACT_CLOCK_MODE=demo uvicorn process.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

No existing call sites change: `seed()` keeps its `(repo, clock, settings) -> dict` signature and return shape, and `reset()` is unchanged (it already calls `reset_all()` + `seed()`).

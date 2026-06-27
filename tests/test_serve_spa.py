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
    # Files vite copies from web/public/ to the dist ROOT (favicon, wordmark, the
    # charity stamps) — these must be served as files, not the SPA shell.
    (dist / "pact_wordmark.png").write_bytes(b"PNG_WORDMARK_BYTES")
    (dist / "charity-stamps").mkdir(parents=True, exist_ok=True)
    (dist / "charity-stamps" / "charity_water.png").write_bytes(b"PNG_STAMP_BYTES")
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


async def test_dist_root_static_files_served_not_spa_shell(monkeypatch, tmp_path):
    """Files vite copies from web/public/ to the dist root (favicon, wordmark,
    charity stamps) are served as real files, NOT swallowed by the SPA fallback."""
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
            r1 = await client.get("/pact_wordmark.png")
            assert r1.status_code == 200
            assert "PACT_SPA_MARKER" not in r1.text
            assert "image/png" in r1.headers["content-type"]

            r2 = await client.get("/charity-stamps/charity_water.png")
            assert r2.status_code == 200
            assert "PACT_SPA_MARKER" not in r2.text
            assert "image/png" in r2.headers["content-type"]
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

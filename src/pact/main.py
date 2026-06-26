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

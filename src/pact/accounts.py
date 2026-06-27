"""Account-link tokens — the seam for tying an external agent to an owner's Pact
account so it claims the right pacts.

STUB: mints a deterministic token per owner and resolves it back. This is NOT
secure (no secret, rotation, or expiry) — it marks where real multi-user agent
auth will live. Today the app is single-owner / local-first, so a stable
per-owner token is enough to wire the connect-your-agent step end to end.
"""

from __future__ import annotations

import hashlib

from pact.clock import Clock
from pact.models import AccountLink


def mint_token(owner: str) -> str:
    """A stable, opaque-looking token for an owner (deterministic stub)."""
    return "pat_" + hashlib.sha1(f"pact-account:{owner}".encode("utf-8")).hexdigest()[:16]


def link_for(owner: str, clock: Clock) -> AccountLink:
    return AccountLink(owner=owner, token=mint_token(owner), created_at=clock.now())

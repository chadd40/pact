"""Account-link tokens — the seam for tying an external agent to an owner's Pact
account so it claims the right pacts.

Tokens are returned to the user exactly once. Pact stores only a SHA-256 hash
plus a short display prefix, so a leaked local database is not itself a bearer
credential.
"""

from __future__ import annotations

from datetime import timedelta
import hashlib
import hmac
import secrets

from pact.clock import Clock
from pact.models import AccountLink


DEFAULT_TOKEN_TTL_DAYS = 90
DEFAULT_SCOPES = ["claim_tasks", "post_results", "relay_outbox", "read_pacts"]


def mint_token(owner: str | None = None) -> str:
    """Return a new opaque bearer token.

    ``owner`` is accepted for compatibility with the old deterministic helper,
    but is intentionally ignored.
    """
    return "pat_" + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_prefix(token: str) -> str:
    return token[:12]


def verify_token(token: str, link: AccountLink) -> bool:
    return hmac.compare_digest(hash_token(token), link.token_hash)


def issue_token(
    owner: str,
    clock: Clock,
    *,
    ttl_days: int = DEFAULT_TOKEN_TTL_DAYS,
    scopes: list[str] | None = None,
) -> tuple[AccountLink, str]:
    raw = mint_token()
    now = clock.now()
    link = AccountLink(
        owner=owner,
        token_hash=hash_token(raw),
        token_prefix=token_prefix(raw),
        created_at=now,
        expires_at=now + timedelta(days=ttl_days),
        scopes=list(scopes or DEFAULT_SCOPES),
    )
    return link, raw


def link_for(owner: str, clock: Clock) -> tuple[AccountLink, str]:
    return issue_token(owner, clock)

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from pact.clock import Clock

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous 0/O/1/I


@dataclass
class _TokenEntry:
    pact_id: str
    expires_at: datetime
    used: bool = False


class TokenStore:
    """In-memory single-use nonce tokens with a TTL (anti-cheat layer 1)."""

    def __init__(self, ttl_minutes: int = 10) -> None:
        self._ttl_minutes = ttl_minutes
        self._tokens: dict[str, _TokenEntry] = {}

    def issue(self, pact_id: str, clock: Clock) -> str:
        token = "PACT-" + "".join(secrets.choice(_ALPHABET) for _ in range(2))
        # Avoid a (vanishingly rare) collision with a live token.
        while token in self._tokens:
            token = "PACT-" + "".join(secrets.choice(_ALPHABET) for _ in range(2))
        expires_at = clock.now() + timedelta(minutes=self._ttl_minutes)
        self._tokens[token] = _TokenEntry(pact_id=pact_id, expires_at=expires_at)
        return token

    def verify(self, pact_id: str, token: str, clock: Clock) -> bool:
        entry = self._tokens.get(token)
        if entry is None:
            return False
        if entry.pact_id != pact_id:
            return False
        if entry.used:
            return False
        if clock.now() > entry.expires_at:
            return False
        entry.used = True
        return True

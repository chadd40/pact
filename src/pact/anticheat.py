from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import imagehash
from PIL import Image

from pact.clock import Clock
from pact.models import Proof, ProofStatus

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


def day_bucket(received_at: datetime, tz: str) -> str:
    """Bucket a server timestamp into a 'YYYY-MM-DD' calendar day in the pact timezone.

    Server time is the source of truth (spec §6). The instant is converted into the
    pact's timezone before the date is taken, so the same UTC instant can land on
    different calendar days for different pact timezones.
    """
    local = received_at.astimezone(ZoneInfo(tz))
    return local.strftime("%Y-%m-%d")


def count_distinct_valid_days(proofs: list[Proof]) -> int:
    """Count distinct day_bucket values among proofs that passed judging.

    At most one valid proof counts per calendar day; failed/ambiguous proofs are
    excluded. This enforces the distinct-day criterion for all-or-nothing verdicts.
    """
    valid_days = {
        proof.day_bucket
        for proof in proofs
        if proof.status == ProofStatus.passed
    }
    return len(valid_days)


def phash_hex(image_path: str) -> str:
    return str(imagehash.phash(Image.open(image_path)))


def find_duplicate(phash: str, existing: list[str], threshold: int = 6) -> int | None:
    target = imagehash.hex_to_hash(phash)
    for i, h in enumerate(existing):
        if (target - imagehash.hex_to_hash(h)) <= threshold:
            return i
    return None

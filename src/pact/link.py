"""Link funding connection — the post-first-pact 'connect a funding source' step.

Pact is charge-on-fail, never escrow: 'connecting' Link does NOT move or hold
money. It registers a funding reference so that, if a pact later fails, the
existing settlement path is allowed to create the donation charge. In this
local-first build the reference is a deterministic TEST value and no real card
or money is ever touched. Live wiring stays gated behind explicit config
(see payment.LinkCliProvider).
"""

from __future__ import annotations

from pact.clock import Clock
from pact.models import LinkAccount


def new_account(owner: str) -> LinkAccount:
    """A fresh, disconnected account for an owner."""
    return LinkAccount(owner=owner)


def connect_account(acct: LinkAccount, clock: Clock) -> LinkAccount:
    """Register a (test) funding source. Idempotent: re-connecting is a no-op."""
    if acct.connected:
        return acct
    return acct.model_copy(
        update={
            "connected": True,
            "funding_ref": f"test_funding_{acct.owner}",
            "connected_at": clock.now(),
        }
    )

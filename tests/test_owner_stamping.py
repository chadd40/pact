"""Agent-created pacts must land under the local account so they appear in the
desktop app (which lists pacts by owner). Historically the agent/skill path saved
pacts with an empty owner, making them invisible."""
from datetime import datetime, timezone

from pact.clock import FixedClock
from pact.config import load_settings
from pact.lifecycle import draft_pact
from pact.reasoning import TestLLMProvider
from pact.repository import Repository


def _clock():
    return FixedClock(datetime(2026, 6, 22, 9, 0, tzinfo=timezone.utc))


def test_draft_pact_stamps_default_owner():
    settings = load_settings({})
    pact = draft_pact(
        "work out 5x this week or $20 to charity", TestLLMProvider(), _clock(), settings
    )
    assert pact.owner == settings.default_owner == "demo@pact.local"


def test_default_owner_is_overridable_by_env():
    settings = load_settings({"PACT_DEFAULT_OWNER": "me@example.com"})
    pact = draft_pact(
        "work out 5x this week or $20 to charity", TestLLMProvider(), _clock(), settings
    )
    assert pact.owner == "me@example.com"


def test_claim_orphan_pacts_reassigns_empty_owner(tmp_path):
    repo = Repository.connect(str(tmp_path / "pact.db"))
    repo.init_schema()
    # An owner-less draft (the old agent-path shape).
    orphan = draft_pact(
        "do a thing 5x this week or $15 to charity", TestLLMProvider(), _clock(), load_settings({})
    )
    orphan.owner = ""  # simulate the historical empty-owner row
    repo.save_pact(orphan)
    assert repo.list_pacts("demo@pact.local") == []

    claimed = repo.claim_orphan_pacts("demo@pact.local")

    assert claimed == 1
    owned = repo.list_pacts("demo@pact.local")
    assert [p.id for p in owned] == [orphan.id]
    # Idempotent: nothing left to claim.
    assert repo.claim_orphan_pacts("demo@pact.local") == 0

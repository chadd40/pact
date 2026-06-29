from datetime import datetime, timezone

import pytest

from pact.clock import FixedClock
from pact.config import Settings
from pact.models import Modality, PactStatus, ProofStatus, StakeState
from pact.anticheat import TokenStore
from pact.reasoning import TestLLMProvider
from pact.lifecycle import (
    PactRefused,
    draft_pact,
    confirm_and_start,
    submit_proof,
)


def _clock() -> FixedClock:
    return FixedClock(datetime(2026, 6, 24, 18, 0, 0, tzinfo=timezone.utc))


def _settings() -> Settings:
    return Settings()


# ---------- draft_pact ----------

def test_draft_pact_builds_draft_with_clamped_recommended_stake():
    clock = _clock()
    settings = _settings()
    provider = TestLLMProvider()
    pact = draft_pact("work out 5x this week or $20 to charity", provider, clock, settings)

    assert pact.status == PactStatus.draft
    assert pact.stake_state == StakeState.none
    assert pact.original_prompt == "work out 5x this week or $20 to charity"
    # recommended clamped into [min, max]
    assert settings.min_stake_cents <= pact.recommended_stake_cents <= settings.max_stake_cents
    # stake defaults to recommended
    assert pact.stake_amount_cents == pact.recommended_stake_cents
    assert pact.created_at == clock.now()
    assert pact.id.startswith("pact_")
    assert pact.rubric.modality == Modality.photo


def test_draft_pact_refusal_raises_pact_refused():
    clock = _clock()
    settings = _settings()
    provider = TestLLMProvider()
    with pytest.raises(PactRefused):
        # TestLLMProvider draft refuses when the prompt asks for self-harm
        draft_pact("lose 10 pounds every single day no rest", provider, clock, settings)


# ---------- confirm_and_start ----------

def _draft(clock, settings, provider) -> "object":
    return draft_pact("work out 5x this week or $20 to charity", provider, clock, settings)


def test_confirm_and_start_activates_and_freezes_charity():
    clock = _clock()
    settings = _settings()
    provider = TestLLMProvider()
    pact = _draft(clock, settings, provider)

    started = confirm_and_start(
        pact, 1000, "against_malaria_foundation", clock, settings, consent_acknowledged=True
    )

    assert started.status == PactStatus.active
    assert started.stake_state == StakeState.committed
    assert started.stake_amount_cents == 1000
    assert started.charity_id == "against_malaria_foundation"
    assert started.charity_url  # frozen, non-empty
    assert started.started_at == clock.now()


def test_confirm_and_start_rejects_stake_above_cap():
    clock = _clock()
    settings = _settings()
    provider = TestLLMProvider()
    pact = _draft(clock, settings, provider)

    with pytest.raises(ValueError):
        confirm_and_start(
            pact, settings.max_stake_cents + 1, "against_malaria_foundation", clock, settings,
            consent_acknowledged=True,
        )


def test_confirm_and_start_rejects_stake_below_cap():
    clock = _clock()
    settings = _settings()
    provider = TestLLMProvider()
    pact = _draft(clock, settings, provider)

    with pytest.raises(ValueError):
        confirm_and_start(
            pact, settings.min_stake_cents - 1, "against_malaria_foundation", clock, settings,
            consent_acknowledged=True,
        )


def test_confirm_and_start_rejects_unknown_charity():
    clock = _clock()
    settings = _settings()
    provider = TestLLMProvider()
    pact = _draft(clock, settings, provider)

    with pytest.raises(ValueError):
        confirm_and_start(
            pact, 1000, "not_a_real_charity", clock, settings, consent_acknowledged=True
        )


# ---------- submit_proof ----------

def _make_image(tmp_path) -> str:
    from PIL import Image

    path = tmp_path / "proof.jpg"
    Image.new("RGB", (64, 64), color=(123, 222, 64)).save(path)
    return str(path)


def test_submit_proof_photo_without_vision_judge_is_held_ambiguous(tmp_path):
    # With only the deterministic fallback (no vision-capable agent connected),
    # an image proof cannot be content-judged, so it is HELD ambiguous for review
    # rather than rubber-stamped as passed. Token + phash are still computed, and
    # the client-supplied content_ok is ignored for images (vision judges content).
    clock = _clock()
    settings = _settings()
    provider = TestLLMProvider()
    tokens = TokenStore()
    pact = confirm_and_start(
        _draft(clock, settings, provider), 1000, "against_malaria_foundation", clock, settings,
        consent_acknowledged=True,
    )
    token = tokens.issue(pact.id, clock)
    image_path = _make_image(tmp_path)

    proof = submit_proof(
        pact,
        Modality.photo,
        token,
        content_ok=True,
        image_path=image_path,
        tokens=tokens,
        provider=provider,
        clock=clock,
    )

    assert proof.pact_id == pact.id
    assert proof.token_ok is True
    assert proof.dup_of is None
    assert proof.status == ProofStatus.ambiguous
    assert proof.judge_checklist == {"token": True, "content": False, "not_dup": True}
    assert proof.received_at == clock.now()
    assert proof.day_bucket  # computed in pact tz
    assert proof.phash  # computed for a photo
    assert proof.id


def test_submit_proof_invalid_token_fails(tmp_path):
    clock = _clock()
    settings = _settings()
    provider = TestLLMProvider()
    tokens = TokenStore()
    pact = confirm_and_start(
        _draft(clock, settings, provider), 1000, "against_malaria_foundation", clock, settings,
        consent_acknowledged=True,
    )
    image_path = _make_image(tmp_path)

    # never issued -> verify() is False
    proof = submit_proof(
        pact,
        Modality.photo,
        "PACT-XX",
        content_ok=True,
        image_path=image_path,
        tokens=tokens,
        provider=provider,
        clock=clock,
    )

    assert proof.token_ok is False
    assert proof.status == ProofStatus.failed


def test_submit_proof_duplicate_phash_fails(tmp_path):
    clock = _clock()
    settings = _settings()
    provider = TestLLMProvider()
    tokens = TokenStore()
    pact = confirm_and_start(
        _draft(clock, settings, provider), 1000, "against_malaria_foundation", clock, settings,
        consent_acknowledged=True,
    )
    image_path = _make_image(tmp_path)

    # first proof: no vision judge -> held ambiguous (still phashed for dedup)
    token1 = tokens.issue(pact.id, clock)
    first = submit_proof(
        pact, Modality.photo, token1, True, image_path,
        tokens, provider, clock,
    )
    assert first.status == ProofStatus.ambiguous

    # resubmit the SAME image -> duplicate phash -> failed
    token2 = tokens.issue(pact.id, clock)
    dup = submit_proof(
        pact, Modality.photo, token2, True, image_path,
        tokens, provider, clock,
        prior_phashes=[first.phash],
    )
    assert dup.dup_of == first.phash
    assert dup.status == ProofStatus.failed

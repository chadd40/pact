"""The NeMo Guardrails ("NemoGuard") spend guard.

Confirms the deterministic policy genuinely runs through the NeMo Guardrails
runtime (rail == 'nemoguard'), and that the per-owner policy is assembled from
the profile's spend limit + the known-charity allowlist.
"""

from pact.guardrails import SpendGuard, policy_for_profile
from pact.models import Profile
from pact.spend_policy import SpendPolicy, SpendRequest


def _req(**overrides) -> SpendRequest:
    base = dict(
        owner="owner@example.com",
        amount_cents=1000,
        charity_id="against_malaria_foundation",
        verified_failure=True,
    )
    base.update(overrides)
    return SpendRequest(**base)


def test_guard_allows_within_policy_runs_through_nemoguard():
    guard = SpendGuard(
        SpendPolicy(
            max_cents=5000,
            charity_allowlist=frozenset({"against_malaria_foundation"}),
        )
    )
    decision = guard.check(_req())
    assert decision.allowed is True
    # The decision must come from the NeMo Guardrails runtime, not the fallback.
    assert decision.rail == "nemoguard"
    assert guard.active_rail == "nemoguard"


def test_guard_denies_over_limit():
    guard = SpendGuard(SpendPolicy(max_cents=500))
    decision = guard.check(_req(amount_cents=1000))
    assert decision.allowed is False
    assert "limit" in decision.reason.lower()
    assert decision.rail == "nemoguard"


def test_guard_denies_unverified_failure():
    guard = SpendGuard(SpendPolicy())
    decision = guard.check(_req(verified_failure=False))
    assert decision.allowed is False


def test_policy_for_profile_uses_spend_limit_and_known_charities():
    profile = Profile(owner="owner@example.com", spend_limit_cents=2500)
    policy = policy_for_profile(profile)
    assert policy.max_cents == 2500
    assert "against_malaria_foundation" in policy.charity_allowlist
    # An unknown merchant (not a Pact charity) is rejected.
    decision = SpendGuard(policy).check(_req(charity_id="not_a_real_charity"))
    assert decision.allowed is False


def test_policy_for_none_profile_has_no_extra_ceiling():
    policy = policy_for_profile(None)
    assert policy.max_cents is None

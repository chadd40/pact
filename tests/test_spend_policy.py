"""The deterministic spend policy the gate enforces before any money moves.

This is the LLM-free core of the spend gate: given a proposed spend and the
owner's policy, decide allow/deny with a human-readable reason. The NeMo
Guardrails wrapper (see test_guardrails.py) runs this same logic through the
guardrails runtime; the lifecycle gate (see test_lifecycle_settle.py) calls it
at the settlement chokepoint.
"""

from pact.spend_policy import GateDecision, SpendPolicy, SpendRequest, evaluate


def _req(**overrides) -> SpendRequest:
    base = dict(
        owner="owner@example.com",
        amount_cents=1000,
        charity_id="against_malaria_foundation",
        verified_failure=True,
    )
    base.update(overrides)
    return SpendRequest(**base)


def test_allows_within_policy():
    policy = SpendPolicy(
        max_cents=5000,
        charity_allowlist=frozenset({"against_malaria_foundation"}),
    )
    decision = evaluate(_req(), policy)
    assert isinstance(decision, GateDecision)
    assert decision.allowed is True


def test_denies_over_spend_limit():
    policy = SpendPolicy(max_cents=500)
    decision = evaluate(_req(amount_cents=1000), policy)
    assert decision.allowed is False
    assert "limit" in decision.reason.lower()


def test_denies_charity_not_on_allowlist():
    policy = SpendPolicy(charity_allowlist=frozenset({"unicef"}))
    decision = evaluate(_req(charity_id="against_malaria_foundation"), policy)
    assert decision.allowed is False
    assert "allowlist" in decision.reason.lower() or "approved charit" in decision.reason.lower()


def test_denies_unverified_failure():
    policy = SpendPolicy()
    decision = evaluate(_req(verified_failure=False), policy)
    assert decision.allowed is False
    assert "verif" in decision.reason.lower()


def test_none_limit_allows_any_amount():
    policy = SpendPolicy(max_cents=None, charity_allowlist=None)
    decision = evaluate(_req(amount_cents=50000), policy)
    assert decision.allowed is True


def test_none_allowlist_allows_any_charity():
    policy = SpendPolicy()
    decision = evaluate(_req(charity_id="some_unlisted_charity"), policy)
    assert decision.allowed is True


def test_limit_boundary_is_inclusive():
    policy = SpendPolicy(max_cents=1000)
    decision = evaluate(_req(amount_cents=1000), policy)
    assert decision.allowed is True


def test_reason_is_human_readable_dollars():
    policy = SpendPolicy(max_cents=500)
    decision = evaluate(_req(amount_cents=2500), policy)
    # surfaces dollar amounts, not raw cents, for the UI + evidence packet
    assert "$25.00" in decision.reason
    assert "$5.00" in decision.reason

"""Pact's safety guardrails — modeled on NVIDIA NeMo Guardrails' rail architecture.

NeMo Guardrails organizes safety as composable *rails* (input rails, output rails,
execution/action rails, dialog rails). Pact implements that same model with two
rails, deterministically:

  * INPUT RAIL  -> ``intake_input_rail`` — screens a pact prompt before it is drafted
    (self-harm, disordered-eating, overtraining, staking another person). This is the
    Pact analogue of a NeMo ``self check input`` / safety input rail (Colang
    ``define flow self check input``), implemented as deterministic category matching.
  * EXECUTION RAIL -> ``SpendGuard`` / ``pact.spend_policy.evaluate`` — guards the one
    irreversible action (spending the user's money) behind verified-failure + an
    approved-charity allowlist + an amount ceiling. This is the Pact analogue of a NeMo
    execution/action rail wrapping a tool call.

These are deterministic implementations of the rail *patterns* — chosen so the money
path's correctness never depends on an LLM round-trip. The seam to run the rails with
the **real** ``nemoguardrails`` runtime (NVIDIA NeMo Guardrails, NIM/Nemotron-backed)
is ``Settings.guardrails_mode`` (``PACT_GUARDRAILS``): ``"deterministic"`` (default,
this module) or ``"nemo"`` (the real library, reserved). When the real runtime is the
one enforcing, the gate reports rail ``"nemoguard"``; today the deterministic gate
honestly reports ``"spend_policy"``.
"""

from __future__ import annotations

from pact.charities import all_charity_ids
from pact.models import Profile
from pact.spend_policy import GateDecision, SpendPolicy, SpendRequest, evaluate


# ── INPUT RAIL — intake safety ──────────────────────────────────────────────
# Modeled on NeMo Guardrails' input rail (``self check input`` flow): a prompt is
# screened BEFORE it becomes a pact. NeMo would phrase each as a Colang flow asking an
# LLM "should the bot refuse?"; Pact uses deterministic category matching so an unsafe
# goal can never reach the draft model. First matching category wins.
# Each entry is (refusal_reason, trigger_substrings).
INTAKE_RAIL_CATEGORIES: list[tuple[str, list[str]]] = [
    (
        "Refusing: self-harm or self-punishment goals are not allowed. "
        "If you're struggling, you're not alone — in the US you can call "
        "or text 988 (Suicide & Crisis Lifeline).",
        ["hurt myself", "harm myself", "punish myself", "self-harm", "self harm", "self-punish"],
    ),
    (
        "Refusing: weight-loss-rate goals (losing a set amount of weight in "
        "a short window) are unsafe to stake.",
        ["lose 5 pounds", "lose 8 pounds", "lose 10 pounds", "lose 15 pounds", "lose 20 pounds",
         "pounds in", "lbs this week", "lbs in", "drop 8 lbs", "drop 10 lbs"],
    ),
    (
        "Refusing: calorie-restriction, fasting, or purging goals are unsafe "
        "to stake. If eating feels out of control, please reach out for "
        "support — in the US you can call or text 988.",
        ["under 800 calories", "calorie deficit", "starve", "fast for", "fasting",
         "purge", "vomit", "skip meals"],
    ),
    (
        "Refusing: 'every single day with no rest' exercise goals are unsafe. "
        "A safe pact caps frequency and bakes in a rest day.",
        ["every single day", "every day with no rest", "no rest", "no days off",
         "7 days straight", "seven days straight", "no rest day"],
    ),
    (
        "Refusing: goals that train through injury or pain are unsafe. "
        "Rest while injured still counts as keeping the pact.",
        ["injury", "injured", "through the pain", "ignore the pain", "push through pain"],
    ),
    (
        "Refusing: a pact can only stake your own behavior — you can't put "
        "someone else on the hook or stake against another person.",
        ["make my brother", "make my sister", "make my friend", "make him pay",
         "make her pay", "make them pay", "if i don't finish", "force my"],
    ),
]


def intake_input_rail(prompt: str) -> str | None:
    """Run the intake input rail over a pact prompt.

    Returns a refusal reason (string) if the goal is unsafe to stake, or ``None`` to
    pass. Modeled on NeMo Guardrails' ``self check input`` rail; deterministic so the
    decision never depends on a model. (An empty prompt is handled by the draft shell,
    not the rail — the rail only judges the safety of real text.)
    """
    lower = prompt.lower()
    for reason, phrases in INTAKE_RAIL_CATEGORIES:
        if any(phrase in lower for phrase in phrases):
            return reason
    return None


# ── EXECUTION RAIL — agent spend ────────────────────────────────────────────
# Modeled on NeMo Guardrails' execution/action rail: a guard wrapped around the one
# irreversible action (spending money), enforced at the settlement chokepoints before
# any ``payment.create_donation``. The decision is the deterministic policy in
# ``pact.spend_policy`` (amount ceiling + approved-charity allowlist + verified miss).
class SpendGuard:
    """A :class:`~pact.spend_policy.SpendGate` over a fixed policy — the execution rail."""

    def __init__(self, policy: SpendPolicy):
        self._policy = policy

    @property
    def active_rail(self) -> str:
        # Honest label: "spend_policy" = the deterministic execution rail (this module),
        # modeled on NeMo Guardrails. The reserved value "nemoguard" means the real
        # nemoguardrails runtime is enforcing (Settings.guardrails_mode="nemo").
        return "spend_policy"

    def check(self, request: SpendRequest) -> GateDecision:
        return evaluate(request, self._policy)


def policy_for_profile(profile: Profile | None) -> SpendPolicy:
    """Build the spend policy for an owner: their configured agent spend limit,
    restricted to Pact's known-charity catalogue (so an unknown merchant is
    rejected), and only on a verified miss."""
    max_cents = profile.spend_limit_cents if profile else None
    return SpendPolicy(
        max_cents=max_cents,
        charity_allowlist=frozenset(all_charity_ids()),
        require_verified_failure=True,
    )


def build_spend_guard(profile: Profile | None) -> SpendGuard:
    """A deterministic spend guard (execution rail) for an owner's policy."""
    return SpendGuard(policy_for_profile(profile))

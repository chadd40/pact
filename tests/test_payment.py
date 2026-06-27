from datetime import datetime, timezone

from pact.models import Modality, Pact, Rubric
from pact.payment import PaymentResult, TestLinkProvider


def _make_pact(
    pact_id: str = "pact_abc123",
    stake_amount_cents: int = 2000,
    charity_id: str = "against_malaria_foundation",
) -> Pact:
    created = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    rubric = Rubric(
        modality=Modality.photo,
        must_show=["person mid/post exercise"],
        min_distinct_days=5,
        count_target=5,
    )
    return Pact(
        id=pact_id,
        owner="colehaddad40@gmail.com",
        original_prompt="work out 5x this week or $20 to charity",
        title="Work out 5x this week",
        goal="Complete 5 workout sessions on 5 distinct days.",
        timezone="America/Los_Angeles",
        deadline_at=datetime(2026, 6, 28, 23, 59, 59, tzinfo=timezone.utc),
        target_count=5,
        recommended_stake_cents=2000,
        stake_amount_cents=stake_amount_cents,
        charity_id=charity_id,
        charity_url="https://againstmalaria.com/donate",
        rubric=rubric,
        created_at=created,
    )


def test_payment_result_is_frozen_dataclass():
    result = PaymentResult(
        provider="test_link",
        status="succeeded",
        provider_ref="test_sr_x",
        payload={"k": "v"},
    )
    assert result.provider == "test_link"
    assert result.status == "succeeded"
    assert result.provider_ref == "test_sr_x"
    assert result.payload == {"k": "v"}


def test_create_donation_returns_succeeded_result():
    provider = TestLinkProvider()
    pact = _make_pact()

    result = provider.create_donation(pact, idempotency_key="pact_abc123:donation")

    assert isinstance(result, PaymentResult)
    assert result.provider == "test_link"
    assert result.status == "succeeded"


def test_provider_ref_is_deterministic_from_pact_and_amount():
    provider = TestLinkProvider()
    pact = _make_pact(pact_id="pact_abc123", stake_amount_cents=2000)

    first = provider.create_donation(pact, idempotency_key="pact_abc123:donation")
    second = provider.create_donation(pact, idempotency_key="pact_abc123:donation")

    assert first.provider_ref == "test_sr_pact_abc123_2000"
    assert first.provider_ref == second.provider_ref


def test_provider_ref_varies_with_pact_id_and_amount():
    provider = TestLinkProvider()

    a = provider.create_donation(
        _make_pact(pact_id="pact_one", stake_amount_cents=500),
        idempotency_key="pact_one:donation",
    )
    b = provider.create_donation(
        _make_pact(pact_id="pact_two", stake_amount_cents=2000),
        idempotency_key="pact_two:donation",
    )

    assert a.provider_ref == "test_sr_pact_one_500"
    assert b.provider_ref == "test_sr_pact_two_2000"
    assert a.provider_ref != b.provider_ref


def test_payload_carries_charity_amount_and_idempotency_key():
    provider = TestLinkProvider()
    pact = _make_pact(
        pact_id="pact_abc123",
        stake_amount_cents=2000,
        charity_id="against_malaria_foundation",
    )

    result = provider.create_donation(pact, idempotency_key="pact_abc123:donation")

    assert result.payload == {
        "charity_id": "against_malaria_foundation",
        "amount_cents": 2000,
        "idempotency_key": "pact_abc123:donation",
        "mode": "test",
    }

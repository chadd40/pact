"""Tier 2 charity checkout — the deterministic, testable logic.

The Playwright driver itself is integration-only (it drives charity: water's live
SPA), but the card parsing, the real-money safety gate, the PAN-free result, and
graceful degradation when Playwright is absent are all unit-tested here.
"""

import json

import pytest

from pact.charity_checkout import (
    build_result,
    load_card,
    parse_args,
    run_checkout,
    should_submit,
)
from pact.payment import _STRIPE_TEST_CARD


def test_load_card_from_nested_shape(tmp_path):
    p = tmp_path / "card.json"
    p.write_text(json.dumps(_STRIPE_TEST_CARD))
    card = load_card(str(p))
    assert card["number"] == "4242424242424242"
    assert card["exp_month"] == 12 and card["exp_year"] == 2030
    assert card["cvc"] == "123"
    assert card["last4"] == "4242"


def test_load_card_from_flat_shape(tmp_path):
    p = tmp_path / "card.json"
    p.write_text(json.dumps({"number": "4000000000000002", "exp_month": 1, "exp_year": 2031, "cvc": "999"}))
    card = load_card(str(p))
    assert card["last4"] == "0002"
    assert card["exp_month"] == 1


def test_load_card_missing_fields_raises(tmp_path):
    p = tmp_path / "card.json"
    p.write_text(json.dumps({"card": {"cvc": "123"}}))
    with pytest.raises(ValueError):
        load_card(str(p))


@pytest.mark.parametrize(
    "mode,confirm,expected",
    [
        ("live", True, True),     # the only combination that moves real money
        ("live", False, False),
        ("live_test", True, False),
        ("dry_run", True, False),
        ("dry_run", False, False),
    ],
)
def test_should_submit_only_on_live_plus_confirm(mode, confirm, expected):
    assert should_submit(mode, confirm) is expected


def test_build_result_is_pan_free_and_shaped():
    r = build_result(
        status="reached_card_step", submitted=False, mode="dry_run",
        donation_url="https://www.charitywater.org/donate", amount_cents=1000,
    )
    assert r["status"] == "reached_card_step"
    assert r["submitted"] is False
    assert set(r) == {
        "status", "submitted", "outcome", "mode", "donation_url",
        "amount_cents", "reference", "screenshot", "error", "note",
    }


def test_run_checkout_degrades_gracefully_without_playwright(tmp_path):
    # Playwright is an optional dep; without it the helper returns a clean error
    # result (never raises), so the API can surface a useful message.
    p = tmp_path / "card.json"
    p.write_text(json.dumps(_STRIPE_TEST_CARD))
    result = run_checkout(
        card_file=str(p),
        donation_url="https://www.charitywater.org/donate",
        amount_cents=1000,
        mode="dry_run",
        confirm=False,
    )
    assert result["submitted"] is False
    # Either playwright is missing (clean error) or present (drove the page).
    assert result["status"] in {"error", "reached_card_step"}


def test_parse_args_defaults_to_safe_mode():
    args = parse_args(["--card-file", "c.json", "--donation-url", "u", "--amount-cents", "1000"])
    assert args.mode == "dry_run"
    assert args.confirm is False

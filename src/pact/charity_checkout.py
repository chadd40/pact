"""Tier 2: complete a charity donation by driving the charity's real donate page
with the provisioned virtual card.

The chosen target is charity: water's live donate flow (a custom SPA with a
give-once/amount step that advances to a Stripe Elements card step).

PAN safety
----------
This module runs as its OWN process, invoked by the API (never imported into the
request handler). It reads the card file, types the card into the page, and
returns ONLY a structured receipt — the PAN/CVC are never returned, logged, or
printed.

Safety gate
-----------
The irreversible "Donate" submit only fires when ``mode == "live"`` AND
``confirm`` is set. In every other mode the helper drives the flow up to (but not
through) the submit and reports ``reached_card_step`` — so the whole path can be
exercised without moving real money. charity: water's live site has no test mode,
so a real donation is the only way to fully verify the final step.

Run directly:
    python -m pact.charity_checkout --card-file <path> --donation-url <url> \
        --amount-cents 1000 --mode live --confirm
"""

from __future__ import annotations

import argparse
import json
import sys


# ── Pure, testable logic (no Playwright, no I/O beyond reading the card file) ──

def load_card(card_file: str) -> dict:
    """Read the card credential file and return the fields needed to fill a
    checkout form. Tolerant of nesting (``{"card": {...}}`` or flat) and of
    common key spellings. Never returns/logs anything beyond what it reads."""
    with open(card_file, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    card = raw.get("card") if isinstance(raw.get("card"), dict) else raw

    def pick(*keys):
        for key in keys:
            value = card.get(key)
            if value not in (None, ""):
                return value
        return None

    number = pick("number", "card_number", "pan")
    exp_month = pick("exp_month", "expMonth", "expiry_month")
    exp_year = pick("exp_year", "expYear", "expiry_year")
    cvc = pick("cvc", "cvv", "cvc2", "security_code")
    if not number or exp_month is None or exp_year is None:
        raise ValueError("card file missing number/expiry")
    return {
        "number": str(number),
        "exp_month": int(exp_month),
        "exp_year": int(exp_year),
        "cvc": str(cvc) if cvc is not None else "",
        "last4": str(number)[-4:],
    }


def should_submit(mode: str, confirm: bool) -> bool:
    """The irreversible donation submit fires ONLY on a deliberate live run.

    charity: water's site has no test mode, so live_test/dry_run drive the form
    but must never click the final Donate (the 4242 test card would be declined
    anyway, and we never want an accidental real charge)."""
    return mode == "live" and bool(confirm)


def build_result(
    *,
    status: str,
    submitted: bool,
    mode: str,
    donation_url: str,
    amount_cents: int,
    reference: str | None = None,
    screenshot: str | None = None,
    error: str | None = None,
    note: str = "",
) -> dict:
    """A PAN-free result record. This is the ONLY thing the helper emits."""
    return {
        "status": status,  # submitted | reached_card_step | error
        "submitted": submitted,
        "mode": mode,
        "donation_url": donation_url,
        "amount_cents": amount_cents,
        "reference": reference,
        "screenshot": screenshot,
        "error": error,
        "note": note,
    }


def _exp_yy(exp_year: int) -> str:
    return f"{exp_year % 100:02d}"


# ── Playwright driver (best-effort against a live third-party SPA) ────────────
#
# Selectors here target charity: water's current donate flow and Stripe Elements.
# A third-party SPA changes over time, so each step is defensive and logged to
# stderr (never the PAN). When the page shifts, tune the selectors below.

_OVERLAY_CLOSE_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "button:has-text('Accept all')",
    "button:has-text('Accept All')",
    # Unbounce marketing popup ("...project doubled") — the recurring blocker.
    ".ub-emb-close",
    ".ub-emb-iframe + .ub-emb-close",
    "[class*='ub-emb'] [class*='close']",
    "a[id*='close']",
    "button[class*='close']",
    "[aria-label='Close']",
    "[aria-label='close']",
    "dialog[aria-label='Cookie consent dialog'] button:has-text('Close')",
]


def _log(msg: str) -> None:
    print(f"[charity_checkout] {msg}", file=sys.stderr)


def _dismiss_overlays(page) -> None:
    """Best-effort: close cookie + Unbounce marketing popups that intercept clicks.
    charity: water raises an Unbounce embed that reliably covers the donate widget,
    so this is called repeatedly through the flow. Tries close buttons in the page
    and inside any ub-emb iframe, plus Escape."""
    for sel in _OVERLAY_CLOSE_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=1500)
                _log(f"dismissed overlay via {sel}")
        except Exception:
            continue
    # The Unbounce popup is often inside its own iframe — reach its close control.
    for fsel in ["iframe[class*='ub-emb']", "iframe[id*='ub-emb']", "iframe[src*='unbounce']"]:
        try:
            frame = page.frame_locator(fsel).first
            for csel in ["[class*='close']", "a[id*='close']", "[aria-label*='close' i]", "button"]:
                btn = frame.locator(csel).first
                if btn.count() and btn.is_visible():
                    btn.click(timeout=1500)
                    _log(f"dismissed ub-emb popup via {fsel} {csel}")
                    break
        except Exception:
            continue
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def _fill_stripe_card(page, card: dict) -> None:
    """Fill Stripe Elements card fields.

    charity: water (verified against the live page) renders each Stripe field in
    its OWN titled iframe ("Secure card number input frame", etc.) — there are
    also hidden controller iframes on js.stripe.com, so matching by title (not
    just src) is what lands on the visible inputs. Each field is tried against a
    couple of selector variants for resilience."""
    exp = f"{card['exp_month']:02d} / {_exp_yy(card['exp_year'])}"

    # Stripe Elements mounts each field in its OWN iframe and ALSO spins up hidden
    # controller iframes on js.stripe.com. Targeting iframes by selector and taking
    # `.first` lands on a hidden controller (verified: input found but "not
    # visible"). Instead scan every live frame and fill the first VISIBLE matching
    # input — robust to single- or multi-iframe Stripe layouts.
    try:
        page.wait_for_timeout(2500)  # let the card step + Stripe iframes mount
    except Exception:
        pass

    def fill_in_any_frame(selectors, value, label) -> bool:
        for frame in page.frames:
            for sel in selectors:
                try:
                    loc = frame.locator(sel).first
                    if loc.count() and loc.is_visible():
                        loc.scroll_into_view_if_needed(timeout=2000)
                        loc.fill(value, timeout=5000)
                        _log(f"filled {label} via {sel}")
                        return True
                except Exception:
                    continue
        return False

    ok_num = fill_in_any_frame(
        ["input[name='cardnumber']", "input[autocomplete='cc-number']"],
        card["number"], "number",
    )
    ok_exp = fill_in_any_frame(
        ["input[name='exp-date']", "input[autocomplete='cc-exp']"],
        exp, "expiry",
    )
    ok_cvc = fill_in_any_frame(
        ["input[name='cvc']", "input[autocomplete='cc-csc']"],
        card["cvc"], "cvc",
    )
    # Postal/ZIP may be a plain page input or its own frame.
    fill_in_any_frame(
        ["input[autocomplete='postal-code']", "input[name='postalCode']", "input[name='postal']"],
        "10001", "postal",
    )

    if not (ok_num and ok_exp and ok_cvc):
        raise RuntimeError(
            f"could not fill all Stripe card fields (number={ok_num} expiry={ok_exp} cvc={ok_cvc})"
        )


def run_checkout(
    *,
    card_file: str,
    donation_url: str,
    amount_cents: int,
    mode: str,
    confirm: bool,
    screenshot_path: str | None = None,
    headless: bool = True,
    timeout_ms: int = 45000,
) -> dict:
    """Drive the donate flow. Returns a PAN-free result dict."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - optional dep
        return build_result(
            status="error", submitted=False, mode=mode, donation_url=donation_url,
            amount_cents=amount_cents, error=f"playwright not installed: {exc}",
            note="install with: pip install playwright && playwright install chromium",
        )

    card = load_card(card_file)
    dollars = f"{amount_cents / 100:.0f}" if amount_cents % 100 == 0 else f"{amount_cents / 100:.2f}"
    submit = should_submit(mode, confirm)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            page.goto(donation_url, wait_until="domcontentloaded")
            # The Unbounce popup appears on a delay, so settle then dismiss twice.
            page.wait_for_timeout(3500)
            _dismiss_overlays(page)
            _dismiss_overlays(page)

            # Step 1: choose one-time and set the amount (re-dismiss first — the
            # popup re-covers the widget intermittently).
            _dismiss_overlays(page)
            try:
                page.get_by_text("Give once", exact=False).first.click(timeout=8000)
            except Exception:
                _log("'Give once' toggle not found — continuing (may already be one-time)")
            amount = page.get_by_role("spinbutton").first
            amount.fill(dollars, timeout=8000)

            # Step 2: advance to the card step. (exact=False matches the "Give"
            # submit; verified to reach the Stripe step.) Then wait for the Stripe
            # card iframe to actually mount before attempting to fill.
            _dismiss_overlays(page)
            page.get_by_role("button", name="Give", exact=False).first.click(timeout=8000)
            try:
                page.wait_for_selector(
                    "iframe[src*='js.stripe.com'], iframe[title*='card' i]", timeout=20000
                )
            except Exception:
                _log("stripe card iframe did not mount within timeout")
            _dismiss_overlays(page)

            # Step 3: fill the card from the file.
            _fill_stripe_card(page, card)

            if screenshot_path:
                try:
                    page.screenshot(path=screenshot_path, full_page=True)
                except Exception:
                    screenshot_path = None

            if not submit:
                return build_result(
                    status="reached_card_step", submitted=False, mode=mode,
                    donation_url=donation_url, amount_cents=amount_cents,
                    screenshot=screenshot_path,
                    note="card filled; submit gated (set mode=live + confirm to donate for real)",
                )

            # Step 4 (gated): the irreversible submit. Real money moves here.
            page.get_by_role("button", name="Donate", exact=False).first.click(timeout=8000)
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            reference = None
            try:
                body = page.inner_text("body")
                for marker in ("confirmation", "thank you", "receipt", "donation id"):
                    if marker in body.lower():
                        reference = "confirmed"
                        break
            except Exception:
                pass
            if screenshot_path:
                try:
                    page.screenshot(path=screenshot_path, full_page=True)
                except Exception:
                    pass
            return build_result(
                status="submitted", submitted=True, mode=mode,
                donation_url=donation_url, amount_cents=amount_cents,
                reference=reference, screenshot=screenshot_path,
                note="donation submitted to charity: water",
            )
        except Exception as exc:  # noqa: BLE001
            shot = None
            if screenshot_path:
                try:
                    page.screenshot(path=screenshot_path, full_page=True)
                    shot = screenshot_path
                except Exception:
                    pass
            return build_result(
                status="error", submitted=False, mode=mode, donation_url=donation_url,
                amount_cents=amount_cents, screenshot=shot, error=str(exc),
                note="checkout flow failed (live SPA selectors may have changed)",
            )
        finally:
            browser.close()


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Complete a charity donation with a provisioned card.")
    parser.add_argument("--card-file", required=True)
    parser.add_argument("--donation-url", required=True)
    parser.add_argument("--amount-cents", type=int, required=True)
    parser.add_argument("--mode", default="dry_run", choices=["dry_run", "live_test", "live"])
    parser.add_argument("--confirm", action="store_true", help="actually submit (only honored in --mode live)")
    parser.add_argument("--screenshot")
    parser.add_argument("--no-headless", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    result = run_checkout(
        card_file=args.card_file,
        donation_url=args.donation_url,
        amount_cents=args.amount_cents,
        mode=args.mode,
        confirm=args.confirm,
        screenshot_path=args.screenshot,
        headless=not args.no_headless,
    )
    # ONLY the PAN-free result reaches stdout.
    print(json.dumps(result))
    return 0 if result["status"] != "error" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

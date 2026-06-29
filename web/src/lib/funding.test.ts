import { describe, expect, it } from "vitest";
import { paymentMethodLabel } from "./funding";
import type { LinkStatus } from "../types";

function link(overrides: Partial<LinkStatus> = {}): LinkStatus {
  return { owner: "demo", connected: true, funding_ref: null, ...overrides };
}

describe("paymentMethodLabel", () => {
  it("shows the real connected card, never a hardcoded number", () => {
    const label = paymentMethodLabel(link({ payment_method_label: "Visa", payment_method_last4: "1881" }));
    expect(label).toBe("Visa •••• 1881");
    expect(label).not.toContain("4242");
  });

  it("falls back to a neutral label (no fake digits) when no card is known", () => {
    expect(paymentMethodLabel(link({ payment_method_last4: null }))).toBe("your connected method");
    expect(paymentMethodLabel(null)).toBe("your connected method");
  });
});

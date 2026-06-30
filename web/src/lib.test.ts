import { describe, it, expect } from "vitest";
import { statusChip, isTerminal } from "./lib";

describe("statusChip — new pre-auth + completion statuses", () => {
  it("awaiting_stake renders as an awaiting chip, not a draft fallthrough", () => {
    const c = statusChip("awaiting_stake" as never);
    expect(c.cls).not.toBe("chip-draft");
    expect(c.label.toLowerCase()).toContain("stake");
  });

  it("donation_complete renders as a donated chip and is terminal", () => {
    const c = statusChip("donation_complete" as never);
    expect(c.cls).not.toBe("chip-draft");
    expect(isTerminal("donation_complete" as never)).toBe(true);
  });
});

import { describe, it, expect } from "vitest";
import { encodeDraft, decodeDraft, type PactDraft } from "./handoff";

const DRAFT: PactDraft = {
  goal: "Run 3x a week",
  what_counts: "A GPS run of >=2 miles counts.",
  frequency: { days_per_week: 3, weeks: 6 },
  stake_amount_cents: 5000,
  charity_id: "against_malaria_foundation",
  agent: "Claude Code",
};

describe("handoff codec", () => {
  it("round-trips a draft", () => {
    const blob = encodeDraft(DRAFT);
    expect(blob.startsWith("pact1:")).toBe(true);
    const r = decodeDraft(blob);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.draft).toEqual(DRAFT);
  });

  it("tolerates surrounding whitespace", () => {
    const r = decodeDraft("  " + encodeDraft(DRAFT) + "\n");
    expect(r.ok).toBe(true);
  });

  it("rejects a non-pact string", () => {
    expect(decodeDraft("hello").ok).toBe(false);
  });

  it("rejects a truncated/corrupted blob (checksum mismatch)", () => {
    const blob = encodeDraft(DRAFT);
    const cut = blob.slice(0, blob.length - 4);
    expect(decodeDraft(cut).ok).toBe(false);
  });

  it("round-trips a draft without what_counts", () => {
    const d: PactDraft = {
      goal: "Meditate",
      frequency: { days_per_week: 7, weeks: 2 },
      stake_amount_cents: 2000,
      charity_id: "against_malaria_foundation",
      agent: "Hermes",
    };
    const r = decodeDraft(encodeDraft(d));
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.draft).toEqual(d);
      expect(r.draft.what_counts).toBeUndefined();
    }
  });

  it("round-trips a draft with goal_template", () => {
    const d: PactDraft = {
      goal: "Work out",
      goal_template: "workout",
      frequency: { days_per_week: 5, weeks: 4 },
      stake_amount_cents: 10000,
      charity_id: "against_malaria_foundation",
      agent: "Hermes",
    };
    const r = decodeDraft(encodeDraft(d));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.draft.goal_template).toBe("workout");
  });

  it("round-trips a draft without goal_template (goal_template stays undefined)", () => {
    const d: PactDraft = {
      goal: "Meditate",
      frequency: { days_per_week: 7, weeks: 2 },
      stake_amount_cents: 2000,
      charity_id: "against_malaria_foundation",
      agent: "Hermes",
    };
    const r = decodeDraft(encodeDraft(d));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.draft.goal_template).toBeUndefined();
  });

  it("rejects a wrong version", () => {
    // hand-build a v2 payload
    const bad =
      "pact1:" +
      btoa(JSON.stringify({ v: 2, kind: "pact-draft", draft: DRAFT }))
        .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    expect(decodeDraft(bad).ok).toBe(false);
  });
});

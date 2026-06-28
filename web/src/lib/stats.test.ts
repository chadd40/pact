import { describe, it, expect } from "vitest";
import { dashboardStats } from "./stats";
import type { Pact, Profile } from "../types";

const pact = (o: Partial<Pact>): Pact => ({ status: "active", stake_amount_cents: 5000, ...(o as object) } as Pact);

describe("dashboardStats", () => {
  it("zeros for a null profile and no pacts", () => {
    expect(dashboardStats(null, [])).toEqual({ currentStreak: 0, bestStreak: 0, winRate: null, activePacts: 0, donatedCents: 0 });
  });
  it("computes win rate, active count and donated sum", () => {
    const profile = { current_streak: 3, best_streak: 9, kept: 3, failed: 1 } as Profile;
    const pacts = [pact({ status: "active" }), pact({ status: "evaluating" }), pact({ status: "donated", stake_amount_cents: 4000 }), pact({ status: "donated", stake_amount_cents: 1000 })];
    expect(dashboardStats(profile, pacts)).toEqual({ currentStreak: 3, bestStreak: 9, winRate: 75, activePacts: 2, donatedCents: 5000 });
  });
});

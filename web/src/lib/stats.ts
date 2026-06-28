import type { Pact, Profile } from "../types";

export interface DashboardStats {
  currentStreak: number;
  bestStreak: number;
  winRate: number | null;
  activePacts: number;
  donatedCents: number;
}

const ACTIVE = new Set(["active", "evaluating"]);

export function dashboardStats(profile: Profile | null, pacts: Pact[]): DashboardStats {
  const kept = profile?.kept ?? 0;
  const failed = profile?.failed ?? 0;
  return {
    currentStreak: profile?.current_streak ?? 0,
    bestStreak: profile?.best_streak ?? 0,
    winRate: kept + failed > 0 ? Math.round((100 * kept) / (kept + failed)) : null,
    activePacts: pacts.filter((p) => ACTIVE.has(p.status)).length,
    donatedCents: pacts.filter((p) => p.status === "donated").reduce((s, p) => s + p.stake_amount_cents, 0),
  };
}

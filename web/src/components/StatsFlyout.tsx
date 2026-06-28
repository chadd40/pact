import { dashboardStats } from "../lib/stats";
import { dollars } from "../lib";
import type { Pact, Profile } from "../types";

export function StatsFlyout({ profile, pacts }: { profile: Profile | null; pacts: Pact[] }) {
  const s = dashboardStats(profile, pacts);
  const items = [
    { label: "Current streak", big: String(s.currentStreak) },
    { label: "Best streak", big: String(s.bestStreak) },
    { label: "Win rate", big: s.winRate == null ? "—" : `${s.winRate}%` },
    { label: "Active pacts", big: String(s.activePacts) },
    { label: "Donated", big: dollars(s.donatedCents) },
  ];
  return (
    <div className="flyout" tabIndex={0}>
      <div className="flyout-panel" role="group" aria-label="Your stats">
        {items.map((it, i) => (
          <div className="flyout-stat" key={it.label}>
            {i > 0 && <span className="flyout-div" aria-hidden="true" />}
            <div className="flyout-stat-num m">{it.big}</div>
            <div className="flyout-stat-label" data-testid="flyout-stat-label">{it.label}</div>
          </div>
        ))}
      </div>
      <div className="flyout-collapsed" aria-hidden="true">
        <span className="flyout-collapsed-num m">{dollars(s.donatedCents)}</span>
        <span className="flyout-collapsed-label">Donated</span>
        <svg className="flyout-chevron" viewBox="0 0 24 24" width="14" height="14"><path d="M15 6l-6 6 6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </div>
    </div>
  );
}

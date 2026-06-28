import { useCallback, useEffect, useMemo, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { api, DEMO_OWNER } from "../api";
import { useDemo } from "../App";
import { AppDataContext, type AppData } from "../data";
import type { Charity, Pact, Profile } from "../types";
import { LogoMenu } from "./LogoMenu";
import { StatsFlyout } from "./StatsFlyout";
import { PactToast } from "./PactToast";

// Stable demo pact ids (src/pact/demo.seed + seed_states) the States menu jumps to.
const JUMPS = [
  { label: "Home", to: "/dashboard", dot: "#6f6a5e" },
  { label: "Active pact", to: "/pact/pact-live", dot: "var(--pc-kept)" },
  { label: "Under review", to: "/pact/pact-review", dot: "var(--pc-amber)" },
  { label: "Verdict · kept", to: "/pact/pact-win", dot: "var(--pc-kept)" },
  { label: "Verdict · failed", to: "/pact/pact-miss", dot: "var(--pc-accent)" },
  { label: "Donation due", to: "/pact/pact-donate", dot: "var(--pc-accent)" },
  { label: "Donated", to: "/pact/pact-fail", dot: "#6f6a5e" },
];

export function AppShell() {
  const { bump, busy, doSeed, doAdvance, doReset } = useDemo();
  const location = useLocation();
  const navigate = useNavigate();
  const [pacts, setPacts] = useState<Pact[]>([]);
  const [pactsLoaded, setPactsLoaded] = useState(false);
  const [charities, setCharities] = useState<Charity[]>([]);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  // Pacts refresh on the demo `bump` signal (shared with Home/Coach via context).
  useEffect(() => {
    let alive = true;
    api.listPacts(DEMO_OWNER)
      .then((p) => { if (alive) { setPacts(p); setPactsLoaded(true); } })
      .catch(() => { if (alive) setPactsLoaded(true); });
    return () => { alive = false; };
  }, [bump]);

  // Profile refresh on bump (mirrors Home.tsx pattern) — needed by StatsFlyout.
  useEffect(() => {
    let alive = true;
    api.profile(DEMO_OWNER).then((p) => alive && setProfile(p)).catch(() => {});
    return () => { alive = false; };
  }, [bump]);

  // Charities are quasi-static: fetch once, cache for every screen.
  useEffect(() => {
    let alive = true;
    api.charities().then((c) => alive && setCharities(c)).catch(() => {});
    return () => { alive = false; };
  }, []);

  const pending = useMemo(() => pacts.find((p) => p.status === "donation_pending"), [pacts]);

  const appData = useMemo<AppData>(
    () => ({
      pacts,
      pactsLoaded,
      charities,
      charityById: Object.fromEntries(charities.map((c) => [c.id, c])),
    }),
    [pacts, pactsLoaded, charities]
  );

  const jump = useCallback((to: string) => { setMenuOpen(false); navigate(to); }, [navigate]);

  return (
    <AppDataContext.Provider value={appData}>
      <div className="as-root">
        {/* ── Top bar ── */}
        <header className="as-topbar">
          <LogoMenu />
          <StatsFlyout profile={profile} pacts={pacts} />
        </header>

        {/* ── Main content ── */}
        <main className="as-main">
          <Outlet />
        </main>

        {/* ── Pending donation toast ── */}
        <PactToast
          pact={pending ?? null}
          onResolve={(id) =>
            navigate(`/pact/${id}`, { state: { backgroundLocation: location } })
          }
        />

        {/* ── States / Demo menu (dev affordance — relocated from sidebar) ── */}
        <div className="as-states">
          {menuOpen && (
            <div className="as-states-menu">
              <div className="as-states-head m">Demo</div>
              <button className="as-states-act" disabled={!!busy} onClick={doSeed}>
                {busy === "seed" ? "Seeding…" : "Seed demo"}
              </button>
              <button className="as-states-act" disabled={!!busy} onClick={doAdvance}>
                {busy === "advance" ? "Advancing…" : "Advance day"}
              </button>
              <button className="as-states-act" disabled={!!busy} onClick={doReset}>
                {busy === "reset" ? "Resetting…" : "Reset"}
              </button>
              <div className="as-states-head m">Jump to state</div>
              {JUMPS.map((j) => (
                <button key={j.label} className="as-states-jump" onClick={() => jump(j.to)}>
                  <span className="as-states-dot" style={{ background: j.dot }} />
                  {j.label}
                </button>
              ))}
            </div>
          )}
          <button className="as-states-toggle" onClick={() => setMenuOpen((o) => !o)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="15" height="15"><circle cx="12" cy="12" r="3" /><path d="M3 12h3M18 12h3M12 3v3M12 18v3" /></svg>
            States
          </button>
        </div>
      </div>
    </AppDataContext.Provider>
  );
}

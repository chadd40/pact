import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api, DEMO_OWNER } from "../api";
import { useDemo } from "../App";
import { dollars } from "../lib";
import type { Pact } from "../types";

// Sidebar nav definition. Coach/Charities/Settings are real pages.
const NAV = [
  { to: "/dashboard", label: "Home", icon: "home" },
  { to: "/coach", label: "Coach", icon: "coach" },
  { to: "/charities", label: "Charities", icon: "heart" },
  { to: "/settings", label: "Settings", icon: "gear" },
];

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

function NavIcon({ name }: { name: string }) {
  const p = {
    home: <><path d="M3 10.5 12 4l9 6.5" /><path d="M5 9.5V20h14V9.5" /></>,
    coach: <path d="M21 11.5a8.4 8.4 0 0 1-12 7.6L3 21l1.9-5.6A8.4 8.4 0 1 1 21 11.5Z" />,
    heart: <path d="M12 20s-7-4.3-7-9.2A3.8 3.8 0 0 1 12 8a3.8 3.8 0 0 1 7-1.2c0 4.9-7 13.2-7 13.2Z" />,
    gear: <><circle cx="12" cy="12" r="3.2" /><path d="M12 3v2.4M12 18.6V21M21 12h-2.4M5.4 12H3M18 6l-1.7 1.7M7.7 16.3 6 18M18 18l-1.7-1.7M7.7 7.7 6 6" /></>,
  }[name];
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="18" height="18">
      {p}
    </svg>
  );
}

export function AppShell() {
  const { bump, busy, doSeed, doAdvance, doReset } = useDemo();
  const location = useLocation();
  const navigate = useNavigate();
  const [pacts, setPacts] = useState<Pact[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    api.listPacts(DEMO_OWNER).then((p) => alive && setPacts(p)).catch(() => {});
    return () => { alive = false; };
  }, [bump]);

  const activeCount = useMemo(
    () => pacts.filter((p) => p.status === "active" || p.status === "evaluating" || p.status === "needs_review").length,
    [pacts]
  );
  const pending = useMemo(() => pacts.find((p) => p.status === "donation_pending"), [pacts]);

  const isActive = (to: string) =>
    to === "/dashboard"
      ? location.pathname === "/dashboard" || location.pathname.startsWith("/pact/")
      : location.pathname === to;

  const jump = useCallback((to: string) => { setMenuOpen(false); navigate(to); }, [navigate]);

  return (
    <div className="as-root">
      {/* ── Sidebar ── */}
      <aside className="as-side">
        <Link to="/dashboard" className="as-brand">
          <span className="as-brand-dot" />
          <span className="as-brand-word">pact</span>
        </Link>
        <nav className="as-nav">
          {NAV.map((n) => (
            <Link key={n.to} to={n.to} className={`as-nav-item${isActive(n.to) ? " on" : ""}`}>
              <NavIcon name={n.icon} />
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="as-profile">
          <div className="as-avatar" aria-hidden="true" />
          <div className="as-profile-text">
            <div className="as-profile-name">Your pacts</div>
            <div className="as-profile-sub m">{activeCount} active</div>
          </div>
        </div>
      </aside>

      {/* ── Main ── */}
      <div className="as-main">
        {pending && (
          <button
            className="as-nag"
            role="alert"
            aria-live="assertive"
            aria-label={`Resolve your ${dollars(pending.stake_amount_cents)} unresolved donation`}
            onClick={() => navigate(`/pact/${pending.id}`)}
          >
            <span className="as-nag-dot" />
            <span className="as-nag-msg">
              Action needed — your {dollars(pending.stake_amount_cents)} stake is unresolved.
            </span>
            <span className="as-nag-tag m">pending</span>
            <span className="as-nag-cta">
              Resolve now
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" width="15" height="15"><path d="M5 12h13M12 6l6 6-6 6" /></svg>
            </span>
          </button>
        )}
        <div className="as-content">
          <Outlet />
        </div>
      </div>

      {/* ── States / Demo menu (dev affordance) ── */}
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
  );
}

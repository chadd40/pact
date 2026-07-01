import { useEffect, useMemo, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useDemo } from "../App";
import { AppDataContext, type AppData } from "../data";
import { useLocalOwner } from "../owner";
import { CHARITY_CATALOG } from "../lib/charities";
import { isDesktop } from "../lib/platform";
import type { Charity, Pact } from "../types";
import { DemoControls } from "./DemoControls";
import { LogoMenu } from "./LogoMenu";
import { NotificationsBell } from "./NotificationsBell";
import { PactToast } from "./PactToast";

export function AppShell() {
  const { bump } = useDemo();
  const navigate = useNavigate();
  const onDashboard = useLocation().pathname === "/dashboard";
  const [owner] = useLocalOwner();
  const [pacts, setPacts] = useState<Pact[]>([]);
  const [pactsLoaded, setPactsLoaded] = useState(false);
  const [charities, setCharities] = useState<Charity[]>(isDesktop() ? [] : CHARITY_CATALOG);

  // Pacts refresh on the demo `bump` signal (shared with Home/Coach via context).
  useEffect(() => {
    let alive = true;
    api.listPacts(owner)
      .then((p) => { if (alive) { setPacts(p); setPactsLoaded(true); } })
      .catch(() => { if (alive) setPactsLoaded(true); });
    return () => { alive = false; };
  }, [bump, owner]);

  // Charities are quasi-static. On the public web funnel there's no sidecar, so we
  // seed straight from the bundled catalog (above) and skip the fetch — no 404. In
  // the desktop app we fetch the live list, falling back to the bundle on error.
  useEffect(() => {
    if (!isDesktop()) return;
    let alive = true;
    api.charities()
      .then((c) => alive && setCharities(c))
      .catch(() => alive && setCharities(CHARITY_CATALOG));
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

  return (
    <AppDataContext.Provider value={appData}>
      <div className="as-root">
        {/* ── Floating logo (top-left, no bar) ── */}
        <div className="as-logo">
          <LogoMenu />
        </div>

        {/* ── Notifications tray (top-right, dashboard only) ── */}
        {onDashboard && <NotificationsBell />}

        {/* ── Main content ── */}
        <main className="as-main">
          <Outlet />
        </main>

        {/* ── Pending donation toast ── */}
        <PactToast
          pact={pending ?? null}
          onResolve={(id) => navigate(`/pact/${id}`)}
        />

        {/* ── Demo control strip (demo clock mode only; drives the real lifecycle) ── */}
        <DemoControls />
      </div>
    </AppDataContext.Provider>
  );
}

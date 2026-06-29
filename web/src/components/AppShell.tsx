import { useEffect, useMemo, useState } from "react";
import { Outlet, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useDemo } from "../App";
import { AppDataContext, type AppData } from "../data";
import { useLocalOwner } from "../owner";
import type { Charity, Pact } from "../types";
import { LogoMenu } from "./LogoMenu";
import { PactToast } from "./PactToast";

export function AppShell() {
  const { bump } = useDemo();
  const navigate = useNavigate();
  const [owner] = useLocalOwner();
  const [pacts, setPacts] = useState<Pact[]>([]);
  const [pactsLoaded, setPactsLoaded] = useState(false);
  const [charities, setCharities] = useState<Charity[]>([]);

  // Pacts refresh on the demo `bump` signal (shared with Home/Coach via context).
  useEffect(() => {
    let alive = true;
    api.listPacts(owner)
      .then((p) => { if (alive) { setPacts(p); setPactsLoaded(true); } })
      .catch(() => { if (alive) setPactsLoaded(true); });
    return () => { alive = false; };
  }, [bump, owner]);

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

  return (
    <AppDataContext.Provider value={appData}>
      <div className="as-root">
        {/* ── Floating logo (top-left, no bar) ── */}
        <div className="as-logo">
          <LogoMenu />
        </div>

        {/* ── Main content ── */}
        <main className="as-main">
          <Outlet />
        </main>

        {/* ── Pending donation toast ── */}
        <PactToast
          pact={pending ?? null}
          onResolve={(id) => navigate(`/pact/${id}`)}
        />
      </div>
    </AppDataContext.Provider>
  );
}

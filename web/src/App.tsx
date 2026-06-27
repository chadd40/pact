import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "./api";
import { formatDateTime } from "./lib";

// ── Demo clock context ──────────────────────────────────────────────────────
// The backend runs on a FixedClock in demo mode. We mirror "now" here so screens
// can render live countdowns and pace against the same instant the server uses.
interface DemoCtx {
  nowIso: string | null;
  nowMs: number;
  setNow: (iso: string) => void;
  refreshNow: () => Promise<void>;
  bump: number; // increments to signal a data refresh across screens
  signalChange: () => void;
}

const DemoContext = createContext<DemoCtx | null>(null);
export const useDemo = () => {
  const ctx = useContext(DemoContext);
  if (!ctx) throw new Error("useDemo outside provider");
  return ctx;
};

export function App() {
  const [nowIso, setNowIso] = useState<string | null>(null);
  const [bump, setBump] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const navigate = useNavigate();
  const location = useLocation();

  const signalChange = useCallback(() => setBump((b) => b + 1), []);

  // Learn the demo clock instant. The advance/reset endpoints echo it directly; on a
  // cold load we probe the WIN pact, whose deadline_at == the clock at seed time
  // (demo.py builds it with deadline_at=now). created_at is offset days earlier, so
  // it must not be used for "now".
  const refreshNow = useCallback(async () => {
    try {
      const win = await api.getPact("pact-win");
      setNowIso(win.deadline_at);
    } catch {
      /* no seeded pact yet */
    }
  }, []);

  const setNow = useCallback((iso: string) => setNowIso(iso), []);

  // Hydrate the clock once on mount so a page reload still shows the demo time.
  useEffect(() => {
    refreshNow();
  }, [refreshNow]);

  // Tick the local mirror of "now" every second so countdowns move.
  const [tick, setTick] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setTick(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  // nowMs: the demo clock instant + elapsed wall time since we last synced it.
  const [syncedAt, setSyncedAt] = useState(Date.now());
  useEffect(() => {
    if (nowIso) setSyncedAt(Date.now());
  }, [nowIso]);
  const baseMs = nowIso ? new Date(nowIso).getTime() : Date.now();
  const nowMs = nowIso ? baseMs + (tick - syncedAt) : tick;

  const doSeed = async () => {
    setBusy("seed");
    try {
      // reset rewinds the clock to the seed instant AND reseeds the three pacts,
      // so it doubles as a clean, repeatable "Seed demo". Falls back to a plain
      // seed if the backend isn't in demo-clock mode (reset/advance need FixedClock).
      const seeded = await api.demoReset().catch(() => api.demoSeed());
      // Stamp owner on each so the profile aggregates them.
      await Promise.all(
        [seeded.win, seeded.fail, seeded.live].map((id) =>
          api.setOwner(id, "demo@pact.local").catch(() => {})
        )
      );
      // WIN's deadline_at == the demo clock instant at seed time.
      const win = await api.getPact(seeded.win);
      setNowIso(win.deadline_at);
      signalChange();
      navigate("/dashboard");
    } finally {
      setBusy(null);
    }
  };

  const doAdvance = async () => {
    setBusy("advance");
    try {
      const res = await api.demoAdvance();
      setNowIso(res.now);
      signalChange();
    } finally {
      setBusy(null);
    }
  };

  const doReset = async () => {
    setBusy("reset");
    try {
      // /demo/reset rewinds the clock and reseeds in one step, returning the ids.
      const seeded = await api.demoReset();
      await Promise.all(
        [seeded.win, seeded.fail, seeded.live].map((id) =>
          api.setOwner(id, "demo@pact.local").catch(() => {})
        )
      );
      const win = await api.getPact(seeded.win);
      setNowIso(win.deadline_at);
      signalChange();
      navigate("/dashboard");
    } finally {
      setBusy(null);
    }
  };

  const ctx: DemoCtx = { nowIso, nowMs, setNow, refreshNow, bump, signalChange };

  const isLanding = location.pathname === "/";

  return (
    <DemoContext.Provider value={ctx}>
      {/* The landing owns its own full-bleed chrome; everywhere else gets the demo console. */}
      {!isLanding && (
        <div className="demobar">
          <div className="demobar-inner">
            <Link to="/dashboard" className="brand">
              <img src="/pact_wordmark.png" alt="Pact" className="brand-wordmark" />
            </Link>
            <span className="demobar-tag mono-label">Demo console</span>
            <div className="demobar-spacer" />
            <span className="demobar-clock data">
              <span className="mono-label" style={{ letterSpacing: "0.12em" }}>
                CLOCK
              </span>{" "}
              {nowIso ? formatDateTime(nowIso) : "—"}
            </span>
            <button className="btn btn-ghost btn-sm" onClick={doSeed} disabled={!!busy}>
              {busy === "seed" ? <span className="spin" /> : null}
              Seed demo
            </button>
            <button
              className="btn btn-ghost btn-sm"
              onClick={doAdvance}
              disabled={!!busy || !nowIso}
            >
              {busy === "advance" ? <span className="spin" /> : null}
              Advance day
            </button>
            <button className="btn btn-ghost btn-sm" onClick={doReset} disabled={!!busy}>
              {busy === "reset" ? <span className="spin" /> : null}
              Reset
            </button>
          </div>
        </div>
      )}

      <main key={location.pathname} className="page-fade">
        <Outlet />
      </main>
    </DemoContext.Provider>
  );
}

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Outlet, useNavigate } from "react-router-dom";
import { api } from "./api";
import { useLocalOwner } from "./owner";

// ── Demo clock + actions context ────────────────────────────────────────────
// The backend runs on a FixedClock in demo mode. We mirror "now" here so screens
// can render live countdowns and pace against the same instant the server uses.
// The demo actions stay in context for tests and internal flows, without a
// user-facing app-shell control.
interface DemoCtx {
  nowIso: string | null;
  setNow: (iso: string) => void;
  refreshNow: () => Promise<void>;
  bump: number; // increments to signal a data refresh across screens
  signalChange: () => void;
  busy: string | null;
  doSeed: () => Promise<void>;
  doAdvance: () => Promise<void>;
  doReset: () => Promise<void>;
}

// Exported so tests can wrap a screen in a stub provider (no network) without
// mounting the full <App> shell. Not used by app code outside this module.
export const DemoContext = createContext<DemoCtx | null>(null);
export const useDemo = () => {
  const ctx = useContext(DemoContext);
  if (!ctx) throw new Error("useDemo outside provider");
  return ctx;
};

// Live demo clock, split into its own context so the 1 Hz tick only re-renders
// the components that actually show a live countdown (PactDetail's dispute window)
// — not the whole tree (sidebar, carousel, ledger).
const ClockContext = createContext<number>(0);
export const useClock = () => useContext(ClockContext);

export function App() {
  const [nowIso, setNowIso] = useState<string | null>(null);
  const [bump, setBump] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [owner] = useLocalOwner();
  const navigate = useNavigate();

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

  const stampOwners = async (ids: { win: string; fail: string; live: string }) => {
    await Promise.all(
      [ids.win, ids.fail, ids.live].map((id) =>
        api.setOwner(id, owner).catch(() => {})
      )
    );
    const win = await api.getPact(ids.win);
    setNowIso(win.deadline_at);
  };

  const doSeed = useCallback(async () => {
    setBusy("seed");
    try {
      // reset rewinds the clock AND reseeds, so it doubles as a clean repeatable
      // seed. Falls back to a plain seed if not in demo-clock mode.
      const seeded = await api.demoReset().catch(() => api.demoSeed());
      await stampOwners(seeded);
      signalChange();
      navigate("/dashboard");
    } finally {
      setBusy(null);
    }
  }, [navigate, signalChange, owner]);

  const doAdvance = useCallback(async () => {
    setBusy("advance");
    try {
      const res = await api.demoAdvance();
      setNowIso(res.now);
      signalChange();
    } finally {
      setBusy(null);
    }
  }, [signalChange]);

  const doReset = useCallback(async () => {
    setBusy("reset");
    try {
      const seeded = await api.demoReset();
      await stampOwners(seeded);
      signalChange();
      navigate("/dashboard");
    } finally {
      setBusy(null);
    }
  }, [navigate, signalChange, owner]);

  // Stable demo context: its identity only changes when nowIso/bump/busy change
  // (the callbacks are useCallback-stable), so the per-second clock tick does NOT
  // re-render DemoContext consumers (sidebar, carousel, ledger, etc.).
  const demoCtx = useMemo<DemoCtx>(
    () => ({ nowIso, setNow, refreshNow, bump, signalChange, busy, doSeed, doAdvance, doReset }),
    [nowIso, setNow, refreshNow, bump, signalChange, busy, doSeed, doAdvance, doReset]
  );

  // Landing (/) and Create (/create) own their own full-bleed chrome and render
  // bare here; the in-app routes are wrapped by <AppShell> (see main.tsx).
  return (
    <DemoContext.Provider value={demoCtx}>
      <ClockContext.Provider value={nowMs}>
        <Outlet />
      </ClockContext.Provider>
    </DemoContext.Provider>
  );
}

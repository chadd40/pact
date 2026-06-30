import { useEffect, useState } from "react";
import { api } from "../api";
import { useDemo } from "../App";
import "./demoControls.css";

/**
 * On-screen demo control strip — shown ONLY in demo clock mode (runtime.clock_mode
 * === "demo"), hidden in real/production builds. It drives the REAL lifecycle on the
 * REAL app (no mock): advance the demo clock past a deadline / dispute window, run the
 * agent (scheduler) sweep to surface nudges, and seed/reset the showcase. Everything
 * here calls the same endpoints the app uses normally — it just compresses time.
 */
export function DemoControls() {
  const { doSeed, doAdvance, doReset, signalChange, busy } = useDemo();
  const [isDemo, setIsDemo] = useState(false);
  const [ticking, setTicking] = useState(false);

  useEffect(() => {
    let alive = true;
    api.runtime()
      .then((r) => { if (alive) setIsDemo(r.clock_mode === "demo"); })
      .catch(() => { /* no sidecar / not demo */ });
    return () => { alive = false; };
  }, []);

  if (!isDemo) return null;

  const runAgent = async () => {
    // One scheduler sweep: settle due, close windows, emit failure/celebrate/reminder
    // nudges — the same pass the autonomous ticker runs under a real clock.
    setTicking(true);
    try { await api.tick(); signalChange(); } finally { setTicking(false); }
  };

  return (
    <div className="demo-controls" role="group" aria-label="Demo controls">
      <span className="demo-controls-tag">DEMO</span>
      <button onClick={() => doAdvance(1)} disabled={!!busy}>+1 day</button>
      <button onClick={() => doAdvance(5)} disabled={!!busy}>+5 days</button>
      <button onClick={runAgent} disabled={ticking}>{ticking ? "Running…" : "Run agent"}</button>
      <button onClick={doSeed} disabled={!!busy}>Seed</button>
      <button onClick={doReset} disabled={!!busy}>Reset</button>
    </div>
  );
}

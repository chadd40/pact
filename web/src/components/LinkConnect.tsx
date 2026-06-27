import { useState } from "react";
import { api } from "../api";

// Post-first-pact "connect a funding source" affordance. Charge-on-fail can only
// fire once a funding source is registered; connecting is a safe local-first stub
// (no money moves). `variant` styles it as a dashboard banner or an in-pact prompt.
interface Props {
  owner: string;
  onConnected: () => void;
  variant?: "banner" | "prompt";
}

export function LinkConnect({ owner, onConnected, variant = "banner" }: Props) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const connect = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.linkConnect(owner);
      onConnected();
    } catch {
      setErr("Couldn't connect. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`link-connect link-connect-${variant}`}>
      <div className="link-connect-body">
        <div className="link-connect-title">Connect a funding source</div>
        <div className="link-connect-text">
          Pact never holds your money. Connecting registers a funding source so your
          stake can actually be charged if you miss — that's what makes the pact real.
          No money moves now.
        </div>
        {err && <div className="link-connect-err">{err}</div>}
      </div>
      <button className="pc-btn link-connect-btn" onClick={connect} disabled={busy}>
        {busy ? "Connecting…" : "Connect Link"}
      </button>
    </div>
  );
}

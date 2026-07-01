import { useState } from "react";
import type { Pact } from "../types";
import { dollars } from "../lib";

export function PactToast({ pact, onResolve }: { pact: Pact | null; onResolve: (id: string) => void }) {
  const [collapsed, setCollapsed] = useState(false);
  if (!pact) return null;
  if (collapsed) {
    return (
      <button className="toast-dot" aria-label="Action needed" onClick={() => setCollapsed(false)}>
        <span className="toast-dot-pulse" aria-hidden="true" />
      </button>
    );
  }
  return (
    <div className="toast" role="alert" aria-live="assertive">
      <button className="toast-x" aria-label="Dismiss" onClick={() => setCollapsed(true)}>×</button>
      <div className="toast-body">
        <div className="toast-title m">Action needed</div>
        <div className="toast-msg">Your {dollars(pact.stake_amount_cents)} stake is unresolved.</div>
      </div>
      <button className="toast-cta" onClick={() => onResolve(pact.id)}>Resolve now</button>
    </div>
  );
}

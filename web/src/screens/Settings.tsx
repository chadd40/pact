import { useCallback, useEffect, useState } from "react";
import { api, DEMO_OWNER } from "../api";
import type { LinkStatus } from "../types";

// Account / funding / agent settings (local-first, single owner).
export function Settings() {
  const [link, setLink] = useState<LinkStatus | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLink(await api.linkStatus(DEMO_OWNER).catch(() => null));
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  const connect = async () => {
    setBusy("link");
    try { await api.linkConnect(DEMO_OWNER); await refresh(); } finally { setBusy(null); }
  };
  const mint = async () => {
    setBusy("token");
    try { const r = await api.mintAgentToken(DEMO_OWNER); setToken(r.token); } finally { setBusy(null); }
  };

  return (
    <div className="pg">
      <div className="pg-head">
        <div className="pg-eyebrow m">Account</div>
        <div className="pg-title">Settings</div>
        <div className="pg-lede">Pact is local-first — one owner, your own agent. Connect a funding source so a missed pact can actually be charged, and link your agent so it can coach you.</div>
      </div>

      <div className="set-card">
        <div className="set-row">
          <div><div className="set-k">Owner</div><div className="set-v m">{DEMO_OWNER}</div></div>
        </div>
      </div>

      <div className="set-card">
        <div className="set-row">
          <div>
            <div className="set-k">Funding source (Link)</div>
            <div className="set-v">
              {link == null ? "—" : link.connected
                ? <span className="set-ok">Connected · {link.funding_ref}</span>
                : "Not connected — a missed pact can't be charged until you connect."}
            </div>
          </div>
          {!link?.connected && (
            <button className="ov-btn sm" onClick={connect} disabled={busy === "link"}>
              {busy === "link" ? "Connecting…" : "Connect Link"}
            </button>
          )}
        </div>
        <div className="set-note m">Pact never holds your money. Connecting registers a (test) funding source — no money moves now.</div>
      </div>

      <div className="set-card">
        <div className="set-row">
          <div>
            <div className="set-k">Your agent</div>
            <div className="set-v">Bring your own agent, install the <span className="m">/pact</span> skill, and paste this token to link it to your account.</div>
          </div>
          <button className="ov-btn sm" onClick={mint} disabled={busy === "token"}>
            {busy === "token" ? "…" : "Generate token"}
          </button>
        </div>
        {token && <div className="set-token m">{token}</div>}
      </div>

      <div className="set-card muted-card">
        <div className="set-k">Demo</div>
        <div className="set-note m">This build runs on a demo clock with seeded pacts. Use the “States” menu (bottom-left) to seed, advance the clock, and jump to any pact state.</div>
      </div>
    </div>
  );
}

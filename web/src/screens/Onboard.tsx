import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, DEMO_OWNER } from "../api";
import { isDesktop } from "../lib/platform";
import type { LinkStatus } from "../types";
import "./onboard.css";

// Result of the native skill installer (web/src-tauri/src/lib.rs::install_pact_skill).
type InstallResult = { status: "installed" | "builtin" | "manual"; path: string | null; message: string };

// Call a Tauri command via the global bridge (withGlobalTauri). Desktop-only.
async function installSkill(agentKey: string): Promise<InstallResult | null> {
  const bridge = (window as unknown as { __TAURI__?: { core?: { invoke?: (c: string, a?: unknown) => Promise<unknown> } } }).__TAURI__;
  if (!bridge?.core?.invoke) return null;
  return (await bridge.core.invoke("install_pact_skill", { agent_key: agentKey })) as InstallResult;
}

export function Onboard() {
  const navigate = useNavigate();
  const pactId = (useLocation().state as { pactId?: string } | null)?.pactId;
  const [link, setLink] = useState<LinkStatus | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [agentKey, setAgentKey] = useState<string | null>(null);
  const [install, setInstall] = useState<InstallResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => { api.linkStatus(DEMO_OWNER).then(setLink).catch(() => setLink(null)); }, []);
  // Learn which agent the user chose when they sealed, so step 2 can install the
  // /pact skill for exactly that agent. Returning users (no pactId) skip this.
  useEffect(() => {
    if (!pactId) return;
    api.getPact(pactId).then((p) => setAgentKey(p.agent ?? null)).catch(() => setAgentKey(null));
  }, [pactId]);

  const connect = async () => {
    setBusy("link");
    try { setLink(await api.linkConnect(DEMO_OWNER)); }
    finally { setBusy(null); }
  };
  const mint = async () => {
    setBusy("token");
    try {
      setToken((await api.mintAgentToken(DEMO_OWNER)).token);
      // On desktop, also install the /pact skill for the chosen agent (M3).
      if (isDesktop()) {
        try { setInstall(await installSkill(agentKey ?? "your agent")); } catch { /* non-fatal: token still works */ }
      }
    } finally { setBusy(null); }
  };

  const fundingDone = !!link?.connected;
  const agentDone = !!token; // the token is the gate; the /pact skill install (M3) rides alongside it.

  return (
    <div className="onb">
      <h1 className="onb-title">Two quick steps to go live</h1>

      <section className={`onb-step ${fundingDone ? "done" : ""}`}>
        <h2>1 · Funding source</h2>
        <p>Connect the card that pays the donation if you miss your pact. Pact never holds your money.</p>
        {fundingDone
          ? <div className="onb-ok">Connected ✓ · {link?.funding_ref}</div>
          : <button className="ov-btn" onClick={connect} disabled={busy === "link"}>{busy === "link" ? "Connecting…" : "Connect Link"}</button>}
      </section>

      <section className={`onb-step ${agentDone ? "done" : ""}`}>
        <h2>2 · Your agent</h2>
        <p>Generate the token your agent uses to claim your pacts and relay coaching. On desktop this also installs the /pact skill for the agent you chose.</p>
        {agentDone
          ? <div className="onb-ok">Token ready ✓ — paste it into your agent</div>
          : <button className="ov-btn" onClick={mint} disabled={busy === "token"}>{busy === "token" ? "…" : "Generate token"}</button>}
        {token && <code className="onb-token">{token}</code>}
        {install && (
          <div className={`onb-install onb-install-${install.status}`}>
            {install.status === "installed" ? "✓ " : ""}{install.message}
          </div>
        )}
      </section>

      <div className="onb-actions">
        <button className="onb-finish" disabled={!fundingDone} onClick={() => navigate("/dashboard")}>
          {fundingDone ? "Go to dashboard" : "Connect funding to continue"}
        </button>
        {pactId && (
          <button
            className="onb-view-pact"
            disabled={!fundingDone}
            onClick={() => navigate(`/pact/${pactId}`)}
          >
            View your pact →
          </button>
        )}
      </div>
    </div>
  );
}

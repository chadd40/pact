import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, DEMO_OWNER } from "../api";
import type { LinkStatus } from "../types";
import "./onboard.css";

export function Onboard() {
  const navigate = useNavigate();
  const pactId = (useLocation().state as { pactId?: string } | null)?.pactId;
  const [link, setLink] = useState<LinkStatus | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => { api.linkStatus(DEMO_OWNER).then(setLink).catch(() => setLink(null)); }, []);

  const connect = async () => {
    setBusy("link");
    try { setLink(await api.linkConnect(DEMO_OWNER)); }
    finally { setBusy(null); }
  };
  const mint = async () => {
    setBusy("token");
    try { setToken((await api.mintAgentToken(DEMO_OWNER)).token); } finally { setBusy(null); }
  };

  const fundingDone = !!link?.connected;
  const agentDone = !!token; // M2: minting the token is the gate; real /pact skill install is M3.

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
        <p>Generate the token your agent uses to claim your pacts and relay coaching. Installing the /pact skill comes next.</p>
        {agentDone
          ? <div className="onb-ok">Token ready ✓ — paste it into your agent</div>
          : <button className="ov-btn" onClick={mint} disabled={busy === "token"}>{busy === "token" ? "…" : "Generate token"}</button>}
        {token && <code className="onb-token">{token}</code>}
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

import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { fundingDisplay, fundingIsLocalOnly, fundingIsReady } from "../lib/funding";
import { isDesktop } from "../lib/platform";
import { useLocalOwner } from "../owner";
import type { ConnectorHealth, LinkStatus, RuntimeInfo } from "../types";
import { AGENTS } from "./Create";
import { RewindIcon, TokenIcon } from "./agentIcons";
import "./onboard.css";

// Result of the native skill installer (web/src-tauri/src/lib.rs::install_pact_skill).
type InstallResult = { status: "installed" | "builtin" | "manual"; path: string | null; message: string };
const AGENT_BASE_URL_KEY = "pact.agentBaseUrl";
const DEFAULT_AGENT_BASE_URL = "http://127.0.0.1:8000";
const LINK_CLI_URL = "https://github.com/stripe/link-cli";
// A plausible token so the demo screen reads as fully wired without minting one.
const DEMO_TOKEN = "pat_demo_9f3a2b7c41";

// Call a Tauri command via the global bridge (withGlobalTauri). Desktop-only.
async function installSkill(agentKey: string): Promise<InstallResult | null> {
  const bridge = (window as unknown as { __TAURI__?: { core?: { invoke?: (c: string, a?: unknown) => Promise<unknown> } } }).__TAURI__;
  if (!bridge?.core?.invoke) return null;
  return (await bridge.core.invoke("install_pact_skill", { agent_key: agentKey })) as InstallResult;
}

// Post-seal setup. Funding + agent are the only things that gate the dashboard;
// billing details and the agent spend limit are managed in Settings (they don't
// block starting a pact). A returning user who is already set up never sees this
// wall — we forward straight to their pact / dashboard. In demo clock mode we
// keep the page visible and render every section in its completed state.
export function Onboard() {
  const navigate = useNavigate();
  const pactId = (useLocation().state as { pactId?: string } | null)?.pactId;
  const [owner] = useLocalOwner();
  const [link, setLink] = useState<LinkStatus | null>(null);
  const [health, setHealth] = useState<ConnectorHealth | null>(null);
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [agentKey, setAgentKey] = useState<string | null>(null);
  const [install, setInstall] = useState<InstallResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);
  const [copiedMcp, setCopiedMcp] = useState(false);
  const [agentBaseUrl, setAgentBaseUrl] = useState(() =>
    window.localStorage.getItem(AGENT_BASE_URL_KEY) ?? ""
  );

  useEffect(() => {
    let cancelled = false;
    async function loadSetup() {
      const [nextRuntime, nextHealth] = await Promise.all([
        api.runtime().catch(() => null),
        api.connectorHealth(owner).catch(() => null),
      ]);
      if (cancelled) return;
      setRuntime(nextRuntime);
      setHealth(nextHealth);
      const live = nextRuntime?.live_money_enabled ?? true;
      const nextLink = await (live ? api.linkPreflight(owner) : api.linkStatus(owner)).catch(() => null);
      if (cancelled) return;
      setLink(nextLink);
      // Idempotent: if funding + agent are already in place (a returning user, or
      // a re-seal), skip the setup wall and go straight to the pact / dashboard.
      // In demo mode we always stay here so the completed screen can be shown.
      const demo = nextRuntime?.clock_mode === "demo";
      const ready = fundingIsReady(nextLink, live) && nextHealth?.agent_token.status === "ready";
      if (ready && !demo) {
        navigate(pactId ? `/pact/${pactId}` : "/dashboard", { replace: true });
        return;
      }
      setChecking(false);
    }
    loadSetup();
    return () => { cancelled = true; };
  }, [owner, pactId, navigate]);
  // Learn which agent the user chose when they sealed, so step 2 can install the
  // /pact skill for exactly that agent. Returning users (no pactId) skip this.
  useEffect(() => {
    if (!pactId) return;
    api.getPact(pactId).then((p) => setAgentKey(p.agent ?? null)).catch(() => setAgentKey(null));
  }, [pactId]);
  useEffect(() => {
    if (!agentBaseUrl && health?.runtime.base_url) {
      setAgentBaseUrl(health.runtime.base_url);
    }
  }, [agentBaseUrl, health?.runtime.base_url]);
  useEffect(() => {
    if (agentBaseUrl.trim()) {
      window.localStorage.setItem(AGENT_BASE_URL_KEY, agentBaseUrl.trim());
    }
  }, [agentBaseUrl]);

  const mint = async () => {
    setBusy("token");
    try {
      setToken((await api.mintAgentToken(owner)).token);
      // On desktop, also install the /pact skill for the chosen agent (M3).
      if (isDesktop()) {
        try { setInstall(await installSkill(agentKey ?? "your agent")); } catch { /* non-fatal: token still works */ }
      }
      setHealth(await api.connectorHealth(owner).catch(() => null));
    } finally { setBusy(null); }
  };
  // The MCP/worker connector flips ready only after an out-of-app step (running the
  // serve command in the agent). Re-probe on demand so a finished user unlocks
  // without having to navigate away and back.
  const recheck = async () => {
    setBusy("recheck");
    try {
      const live = runtime?.live_money_enabled ?? true;
      const [nextHealth, nextLink] = await Promise.all([
        api.connectorHealth(owner).catch(() => null),
        (live ? api.linkPreflight(owner) : api.linkStatus(owner)).catch(() => null),
      ]);
      if (nextHealth) setHealth(nextHealth);
      if (nextLink) setLink(nextLink);
    } finally { setBusy(null); }
  };

  const demoMode = runtime?.clock_mode === "demo";
  const liveMoneyEnabled = runtime?.live_money_enabled ?? true;
  const agentDone = demoMode || !!token || health?.agent_token.status === "ready";
  const fundingDone = demoMode || fundingIsReady(link, liveMoneyEnabled);
  const localOnlyFunding = fundingIsLocalOnly(link, liveMoneyEnabled) || (demoMode && !liveMoneyEnabled);
  const fundingLabel =
    fundingDisplay(link, liveMoneyEnabled) ?? (demoMode ? (liveMoneyEnabled ? "Link connector ready" : "Local-only Link ready") : null);
  const fundingError = !fundingDone && link?.error ? link.error : null;
  const workerStatus = demoMode ? "online" : (health?.worker.status ?? "offline");
  const agentName = agentKey ?? "Hermes";
  const agentDef = AGENTS.find((a) => a.key === agentName) ?? AGENTS[0];
  const canOpenDashboard = fundingDone && agentDone;
  const serveBaseUrl = (agentBaseUrl || health?.runtime.base_url || DEFAULT_AGENT_BASE_URL).trim();
  const commandToken = token ?? (demoMode ? DEMO_TOKEN : "<paste your token>");
  const serveCommand = `pact serve --base-url ${serveBaseUrl} --agent-token ${commandToken}`;
  const agentNote = agentDone
    ? `Run this in ${agentDef.name} so it can act on your pacts, claim tasks, coach you, and pay a missed donation.`
    : `Generate the token and install the /pact skill for ${agentDef.name}, then run this so it can act on your pacts.`;
  useEffect(() => {
    setCopiedMcp(false);
  }, [serveCommand]);
  const copyMcpCommand = async () => {
    try {
      await navigator.clipboard.writeText(serveCommand);
      setCopiedMcp(true);
      window.setTimeout(() => setCopiedMcp(false), 1800);
    } catch {
      setCopiedMcp(false);
    }
  };

  if (checking) {
    return (
      <div className="onb">
        <div className="onb-card onb-checking">Checking your setup…</div>
      </div>
    );
  }

  const headline = canOpenDashboard
    ? "You're all set"
    : pactId ? "Your pact is sealed" : "You're almost set";
  const subcopy = canOpenDashboard
    ? `Link and ${agentDef.name} are connected. Open your dashboard to start.`
    : pactId
      ? `Connect Link and ${agentDef.name}, then open your dashboard.`
      : "Two connections and Pact is ready to hold you to it.";

  return (
    <div className="onb">
      <div className="onb-page" role="region" aria-label={`${agentName} setup`}>
        <header className="onb-head">
          <div className="onb-eyebrow">Setup</div>
          <h1 className="onb-title">{headline}</h1>
          <p className="onb-lede">{subcopy}</p>
        </header>

        {/* At-a-glance status strip, mirroring the Settings overview. */}
        <div className="onb-overview">
          <div className="onb-ov-item">
            <span>Link</span>
            <strong className={fundingDone ? "ok" : undefined}>
              {fundingDone ? "Connected" : "Not connected"}
            </strong>
          </div>
          <div className="onb-ov-item">
            <span>Agent</span>
            <strong className={agentDone ? "ok" : undefined}>
              {agentDone ? "Ready" : "Needs token"}
            </strong>
          </div>
        </div>

        {/* ── Link CLI ──────────────────────────────────────────────────────── */}
        <section className="onb-card">
          <div className="onb-row">
            <div className="onb-row-main">
              <h2 className="onb-k">Link CLI</h2>
              {fundingDone ? (
                <>
                  <div className="onb-v">
                    <span className="onb-ok">
                      Link CLI connected{fundingLabel ? ` · ${fundingLabel}` : ""}
                    </span>
                  </div>
                  {localOnlyFunding && (
                    <div className="onb-note">No real card is connected in this packaged build.</div>
                  )}
                </>
              ) : (
                <>
                  <div className="onb-v">
                    Link is the card Pact charges to your chosen charity if you miss a pact.
                  </div>
                  {fundingError && <div className="onb-err">{fundingError}</div>}
                </>
              )}
            </div>
            {!fundingDone && (
              <a className="onb-install" href={LINK_CLI_URL} target="_blank" rel="noreferrer">
                Install Link CLI
              </a>
            )}
          </div>
        </section>

        {/* ── Connect your agent ────────────────────────────────────────────── */}
        <section className="onb-card">
          <div className="onb-row">
            <div className="onb-row-main">
              <h2 className="onb-k">Connect your agent</h2>
              <div className="onb-v">{agentNote}</div>
            </div>
          </div>
          <label className="onb-field">
            <span className="onb-field-label">Local Pact API URL</span>
            <input
              className="onb-input"
              value={serveBaseUrl}
              onChange={(e) => setAgentBaseUrl(e.target.value)}
              spellCheck={false}
            />
          </label>
          <code className="onb-code">{serveCommand}</code>
          <div className="onb-toolbar">
            <button
              type="button"
              className="onb-gen"
              aria-label={agentDone ? "Regenerate token" : "Generate token"}
              onClick={mint}
              disabled={busy === "token"}
            >
              <TokenIcon />
            </button>
            <button
              type="button"
              className={`onb-copy${copiedMcp ? " is-copied" : ""}`}
              aria-label={copiedMcp ? "Serve command copied" : "Copy serve command"}
              onClick={copyMcpCommand}
            >
              {copiedMcp ? "Copied" : "Copy command"}
            </button>
            <button
              type="button"
              className={`onb-recheck${busy === "recheck" ? " is-busy" : ""}`}
              aria-label="Re-check agent"
              onClick={recheck}
              disabled={busy === "recheck"}
            >
              <RewindIcon />
            </button>
          </div>
          {agentDone && (
            <div className="onb-hint">
              Token {health?.agent_token.token_prefix ?? "ready"} · {agentDef.name}{" "}
              {workerStatus === "online" ? "serving" : "not serving yet"}
            </div>
          )}
          {install && (
            <div className={`onb-install-note${install.status === "installed" ? " is-ok" : ""}`}>
              {install.status === "installed" ? "✓ " : ""}{install.message}
            </div>
          )}
        </section>

        {/* ── Footer ────────────────────────────────────────────────────────── */}
        <footer className="onb-footer">
          <button
            className="onb-primary"
            disabled={!canOpenDashboard}
            onClick={() => navigate("/dashboard")}
          >
            {canOpenDashboard ? "Open dashboard" : "Finish setup to open dashboard"}
          </button>
          {pactId && (
            <button className="onb-secondary" onClick={() => navigate(`/pact/${pactId}`)}>
              View pact
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}

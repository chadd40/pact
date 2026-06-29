import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { ChatShell, StatusPill, type ChatMessage } from "../components/ChatShell";
import { fundingDisplay, fundingIsLocalOnly, fundingIsReady } from "../lib/funding";
import { isDesktop } from "../lib/platform";
import { useLocalOwner } from "../owner";
import type { ConnectorHealth, LinkStatus, RuntimeInfo } from "../types";
import { AGENTS } from "./Create";
import "./onboard.css";

// Result of the native skill installer (web/src-tauri/src/lib.rs::install_pact_skill).
type InstallResult = { status: "installed" | "builtin" | "manual"; path: string | null; message: string };
const AGENT_BASE_URL_KEY = "pact.agentBaseUrl";
const DEFAULT_AGENT_BASE_URL = "http://127.0.0.1:8000";

// Call a Tauri command via the global bridge (withGlobalTauri). Desktop-only.
async function installSkill(agentKey: string): Promise<InstallResult | null> {
  const bridge = (window as unknown as { __TAURI__?: { core?: { invoke?: (c: string, a?: unknown) => Promise<unknown> } } }).__TAURI__;
  if (!bridge?.core?.invoke) return null;
  return (await bridge.core.invoke("install_pact_skill", { agent_key: agentKey })) as InstallResult;
}

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
      if (!cancelled) setLink(nextLink);
    }
    loadSetup();
    return () => { cancelled = true; };
  }, [owner]);
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

  const connect = async () => {
    setBusy("link");
    try { setLink(await api.linkConnect(owner)); }
    finally { setBusy(null); }
  };
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

  const agentDone = !!token || health?.agent_token.status === "ready";
  const liveMoneyEnabled = runtime?.live_money_enabled ?? true;
  const fundingDone = fundingIsReady(link, liveMoneyEnabled);
  const localOnlyFunding = fundingIsLocalOnly(link, liveMoneyEnabled);
  const fundingLabel = fundingDisplay(link, liveMoneyEnabled);
  const fundingIssue = !fundingDone && link?.error ? link.error : null;
  const mcpReady = health?.connectors.some((connector) => connector.key === "mcp" && connector.status === "ready");
  const workerStatus = health?.worker.status ?? "offline";
  const agentName = agentKey ?? "Hermes";
  const agentDef = AGENTS.find((a) => a.key === agentName) ?? AGENTS[0];
  const canOpenDashboard = fundingDone && agentDone && !!mcpReady;
  const mcpBaseUrl = (agentBaseUrl || health?.runtime.base_url || DEFAULT_AGENT_BASE_URL).trim();
  const mcpCommand = `pact mcp --base-url ${mcpBaseUrl} --agent-token <agent-token>`;
  useEffect(() => {
    setCopiedMcp(false);
  }, [mcpCommand]);
  const copyMcpCommand = async () => {
    try {
      await navigator.clipboard.writeText(mcpCommand);
      setCopiedMcp(true);
      window.setTimeout(() => setCopiedMcp(false), 1800);
    } catch {
      setCopiedMcp(false);
    }
  };
  const messages: ChatMessage[] = [
    {
      id: "sealed",
      role: "agent",
      body: createdSetupCopy(agentDef.name, pactId),
    },
    {
      id: "link",
      role: "system",
      meta: "Link funding check",
      body: (
        <div className="onb-check-block">
          <div className="onb-check-row">
            <span>
              {fundingDone
                ? localOnlyFunding ? fundingLabel : `Connected${fundingLabel ? ` · ${fundingLabel}` : ""}`
                : fundingIssue ?? "Connect the funding source that backs missed pacts."}
            </span>
            <StatusPill tone={fundingDone ? "ok" : busy === "link" ? "busy" : "warn"}>
              {fundingDone ? "ready" : busy === "link" ? "checking" : "needs setup"}
            </StatusPill>
          </div>
          {localOnlyFunding && (
            <div className="onb-check-note">No real card is connected in this packaged build.</div>
          )}
        </div>
      ),
      actions: fundingDone ? null : (
        <button className="onb-action" onClick={connect} disabled={busy === "link"}>
          {busy === "link" ? "Connecting..." : "Connect Link"}
        </button>
      ),
    },
    {
      id: "agent",
      role: "system",
      meta: "Agent token",
      body: (
        <div className="onb-check-row">
          <span>{agentDone ? `Token ${health?.agent_token.token_prefix ?? "ready"}` : "Generate the token your agent uses to claim Pact tasks."}</span>
          <StatusPill tone={agentDone ? "ok" : busy === "token" ? "busy" : "warn"}>
            {agentDone ? "ready" : busy === "token" ? "minting" : "missing"}
          </StatusPill>
        </div>
      ),
      actions: (
        <button className="onb-action" onClick={mint} disabled={busy === "token"}>
          {busy === "token" ? "Minting..." : agentDone ? "Regenerate token" : "Generate token"}
        </button>
      ),
    },
    {
      id: "mcp",
      role: "system",
      meta: "MCP server",
      body: (
        <div className="onb-mcp">
          <div className="onb-check-row">
            <span>{mcpReady ? "MCP server ready" : "Add the local Pact MCP server to your agent."}</span>
            <StatusPill tone={mcpReady ? "ok" : "warn"}>{mcpReady ? "ready" : "waiting"}</StatusPill>
          </div>
          <label className="onb-url-field">
            <span className="m">Local Pact API URL</span>
            <input
              value={mcpBaseUrl}
              onChange={(e) => setAgentBaseUrl(e.target.value)}
              spellCheck={false}
            />
          </label>
          <div className="onb-command-row">
            <code className="onb-command">{mcpCommand}</code>
            <button
              type="button"
              className="onb-copy"
              aria-label={copiedMcp ? "MCP command copied" : "Copy MCP command"}
              onClick={copyMcpCommand}
            >
              {copiedMcp ? "Copied" : "Copy command"}
            </button>
          </div>
        </div>
      ),
    },
    {
      id: "worker",
      role: "system",
      meta: "Live agent check",
      body: (
        <div className="onb-check-row">
          <span>Worker {workerStatus}</span>
          <StatusPill tone={workerStatus === "online" ? "ok" : "warn"}>
            {health?.capabilities.vision ? "vision on" : "vision waiting"}
          </StatusPill>
        </div>
      ),
    },
    {
      id: "dashboard",
      role: "agent",
      body: canOpenDashboard
        ? "Everything needed to start is in place. Open your dashboard and I'll keep the pact moving from there."
        : "I'll unlock the dashboard once funding and the agent connector are ready.",
      actions: (
        <div className="onb-chat-actions">
          <button
            className="onb-dashboard"
            disabled={!canOpenDashboard}
            onClick={() => navigate("/dashboard")}
          >
            {canOpenDashboard ? "Dashboard" : "Finish setup to open dashboard"}
          </button>
          {pactId && (
            <button
              className="onb-view-pact"
              disabled={!fundingDone}
              onClick={() => navigate(`/pact/${pactId}`)}
            >
              View pact
            </button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="onb">
      <div className="onb-card">
        <ChatShell
          label={`${agentName} setup chat`}
          agentName={agentDef.name}
          agentAvatar={agentDef.avatar}
          messages={messages}
        />
        {(token || install) && (
          <div className="onb-secret">
            {token && <code className="onb-token">{token}</code>}
            {install && (
              <div className={`onb-install onb-install-${install.status}`}>
                {install.status === "installed" ? "✓ " : ""}{install.message}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function createdSetupCopy(agentName: string, pactId?: string): string {
  if (pactId) {
    return `Your pact is sealed. I'm going to check Link and the ${agentName} connector before I send you to the dashboard.`;
  }
  return `Let's check Link and the ${agentName} connector before you start another pact.`;
}

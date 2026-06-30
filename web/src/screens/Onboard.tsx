import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { ChatShell, StatusPill, type ChatMessage } from "../components/ChatShell";
import { fundingDisplay, fundingIsLocalOnly, fundingIsReady } from "../lib/funding";
import { isDesktop } from "../lib/platform";
import { useLocalOwner } from "../owner";
import type { BillingProfile, ConnectorHealth, LinkStatus, RuntimeInfo, SpendPolicy } from "../types";
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
  const [policy, setPolicy] = useState<SpendPolicy | null>(null);
  const [limitDraft, setLimitDraft] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [agentKey, setAgentKey] = useState<string | null>(null);
  const [install, setInstall] = useState<InstallResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [billing, setBillingState] = useState<BillingProfile | null>(null);
  const [billingDraft, setBillingDraft] = useState<BillingProfile>({ owner });
  const [copiedMcp, setCopiedMcp] = useState(false);
  const [agentBaseUrl, setAgentBaseUrl] = useState(() =>
    window.localStorage.getItem(AGENT_BASE_URL_KEY) ?? ""
  );

  useEffect(() => {
    let cancelled = false;
    async function loadSetup() {
      const [nextRuntime, nextHealth, nextPolicy, nextBilling] = await Promise.all([
        api.runtime().catch(() => null),
        api.connectorHealth(owner).catch(() => null),
        api.getPolicy(owner).catch(() => null),
        api.getBilling(owner).catch(() => null),
      ]);
      if (cancelled) return;
      setRuntime(nextRuntime);
      setHealth(nextHealth);
      setPolicy(nextPolicy);
      if (nextBilling) {
        setBillingState(nextBilling);
        setBillingDraft(nextBilling);
      }
      setLimitDraft(
        nextPolicy?.spend_limit_cents != null
          ? (nextPolicy.spend_limit_cents / 100).toString()
          : ""
      );
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
  const saveLimit = async () => {
    const trimmed = limitDraft.trim();
    const cents = trimmed === "" ? null : Math.round(parseFloat(trimmed) * 100);
    if (cents !== null && (Number.isNaN(cents) || cents < 0)) return;
    setBusy("limit");
    try {
      const next = await api.setPolicy(owner, cents);
      setPolicy(next);
      setLimitDraft(
        next.spend_limit_cents != null ? (next.spend_limit_cents / 100).toString() : ""
      );
    } finally { setBusy(null); }
  };
  const saveBilling = async () => {
    setBusy("billing");
    try {
      const saved = await api.setBilling({ ...billingDraft, owner });
      setBillingState(saved);
      setBillingDraft(saved);
    } finally { setBusy(null); }
  };
  // The MCP/worker connector flips ready only after an out-of-app step (pasting the
  // command into the agent). Re-probe on demand so a finished user unlocks without
  // having to navigate away and back.
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

  const agentDone = !!token || health?.agent_token.status === "ready";
  const liveMoneyEnabled = runtime?.live_money_enabled ?? true;
  const fundingDone = fundingIsReady(link, liveMoneyEnabled);
  const localOnlyFunding = fundingIsLocalOnly(link, liveMoneyEnabled);
  const fundingLabel = fundingDisplay(link, liveMoneyEnabled);
  const fundingIssue = !fundingDone && link?.error ? link.error : null;
  const workerStatus = health?.worker.status ?? "offline";
  const billingDone = !!(
    billing?.first_name && billing?.last_name && billing?.street && billing?.postal_code
  );
  const agentName = agentKey ?? "Hermes";
  const agentDef = AGENTS.find((a) => a.key === agentName) ?? AGENTS[0];
  const canOpenDashboard = fundingDone && billingDone && agentDone;
  const serveBaseUrl = (agentBaseUrl || health?.runtime.base_url || DEFAULT_AGENT_BASE_URL).trim();
  const serveCommand = `pact serve --base-url ${serveBaseUrl} --agent-token ${token ?? "<paste your token>"}`;
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
                : fundingIssue ?? "Connect Link on this device — the card Pact uses if you miss a pact."}
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
      id: "billing",
      role: "system",
      meta: "Billing details",
      body: (
        <div className="onb-check-block">
          <div className="onb-check-row">
            <span>
              {billingDone
                ? `${billing?.first_name} ${billing?.last_name} · ${billing?.postal_code}`
                : "Add the name + address your agent enters on the charity's donation form."}
            </span>
            <StatusPill tone={billingDone ? "ok" : busy === "billing" ? "busy" : "warn"}>
              {billingDone ? "ready" : busy === "billing" ? "saving" : "needs setup"}
            </StatusPill>
          </div>
          <form className="onb-limit-form" onSubmit={(e) => { e.preventDefault(); saveBilling(); }}>
            {([
              ["first_name", "First name"], ["last_name", "Last name"], ["email", "Billing email"],
              ["street", "Street"], ["city", "City"], ["state", "State"],
              ["postal_code", "Postal code"], ["country", "Country"],
            ] as [keyof BillingProfile, string][]).map(([field, label]) => (
              <label className="onb-url-field" key={field}>
                <span className="m">{label}</span>
                <input
                  aria-label={label}
                  value={(billingDraft[field] as string | null | undefined) ?? ""}
                  onChange={(e) => setBillingDraft({ ...billingDraft, [field]: e.target.value })}
                />
              </label>
            ))}
            <button className="onb-action" type="submit" disabled={busy === "billing"}>
              {busy === "billing" ? "Saving..." : "Save billing"}
            </button>
          </form>
          <div className="onb-check-note">
            Your agent enters these on the charity's form when a missed pact pays out — Link can't supply them.
          </div>
        </div>
      ),
    },
    {
      id: "policy",
      role: "system",
      meta: "Agent spend limit",
      body: (
        <div className="onb-check-block">
          <div className="onb-check-row">
            <span>
              {policy == null
                ? "Checking the agent spend limit."
                : policy.spend_limit_cents == null
                  ? "No extra agent spend limit set."
                  : `Agent may spend up to ${formatPolicyLimit(policy.spend_limit_cents)} per missed pact.`}
            </span>
            <StatusPill tone={policy == null || busy === "limit" ? "busy" : "ok"}>
              {policy == null || busy === "limit" ? "checking" : policy.rail === "nemoguard" ? "NemoGuard" : "NeMo-modeled"}
            </StatusPill>
          </div>
          <div className="onb-check-note">Your standing authorization: if you miss, your agent handles the donation to your chosen charity, up to this limit. The spend rail — modeled on NVIDIA NeMo Guardrails — checks every charge.</div>
          <form
            className="onb-limit-form"
            onSubmit={(event) => { event.preventDefault(); saveLimit(); }}
          >
            <label className="onb-url-field">
              <span className="m">Limit per miss</span>
              <input
                aria-label="Agent spend limit"
                type="number"
                min="0"
                step="0.01"
                placeholder="No limit"
                value={limitDraft}
                onChange={(e) => setLimitDraft(e.target.value)}
              />
            </label>
            <button className="onb-action" type="submit" disabled={busy === "limit"}>
              {busy === "limit" ? "Saving..." : "Save spend limit"}
            </button>
          </form>
        </div>
      ),
    },
    {
      id: "agent",
      role: "system",
      meta: "Connect your agent",
      body: (
        <div className="onb-mcp">
          <div className="onb-check-row">
            <span>
              {agentDone
                ? `Token ${health?.agent_token.token_prefix ?? "ready"} · ${agentDef.name} ${workerStatus === "online" ? "serving" : "not serving yet"}`
                : "Generate the token and install the /pact skill for your agent."}
            </span>
            <StatusPill tone={agentDone ? "ok" : busy === "token" ? "busy" : "warn"}>
              {agentDone ? "ready" : busy === "token" ? "minting" : "missing"}
            </StatusPill>
          </div>
          <label className="onb-url-field">
            <span className="m">Local Pact API URL</span>
            <input
              value={serveBaseUrl}
              onChange={(e) => setAgentBaseUrl(e.target.value)}
              spellCheck={false}
            />
          </label>
          <div className="onb-check-note">
            Then run this in {agentDef.name} so it can act on your pacts — claim tasks, coach you, and pay a missed donation:
          </div>
          <div className="onb-command-row">
            <code className="onb-command">{serveCommand}</code>
            <button
              type="button"
              className="onb-copy"
              aria-label={copiedMcp ? "Serve command copied" : "Copy serve command"}
              onClick={copyMcpCommand}
            >
              {copiedMcp ? "Copied" : "Copy command"}
            </button>
          </div>
          <div className="onb-check-row">
            <span>Agent {workerStatus === "online" ? "connected & serving" : "not serving yet"}</span>
            <button
              type="button"
              className="onb-copy"
              onClick={recheck}
              disabled={busy === "recheck"}
            >
              {busy === "recheck" ? "Checking…" : "Re-check"}
            </button>
          </div>
        </div>
      ),
      actions: (
        <button className="onb-action" onClick={mint} disabled={busy === "token"}>
          {busy === "token" ? "Minting..." : agentDone ? "Regenerate token" : "Generate token"}
        </button>
      ),
    },
    {
      id: "dashboard",
      role: "agent",
      body: canOpenDashboard
        ? "Everything needed to start is in place. Open your dashboard and I'll keep the pact moving from there."
        : "I'll unlock the dashboard once funding, billing, and your agent are ready.",
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

function formatPolicyLimit(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

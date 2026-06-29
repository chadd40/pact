import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { fundingDisplay, fundingIsLocalOnly, fundingIsReady } from "../lib/funding";
import { useLocalOwner } from "../owner";
import type { ConnectorEntry, ConnectorHealth, LinkStatus, RuntimeInfo, SpendPolicy } from "../types";

function statusLabel(status: string): string {
  return status.replace(/_/g, " ");
}

function statusClass(status: string): string {
  if (["ready", "online", "installed"].includes(status)) return "ok";
  if (["missing", "needs_token", "needs_install", "offline"].includes(status)) return "warn";
  return "muted";
}

function ConnectorRow({ connector }: { connector: ConnectorEntry }) {
  return (
    <div className="set-conn-row">
      <div>
        <div className="set-conn-name">{connector.name}</div>
        <div className="set-conn-detail">{connector.detail}</div>
      </div>
      <span className={`set-badge ${statusClass(connector.status)}`}>
        {statusLabel(connector.status)}
      </span>
    </div>
  );
}

// Account / funding / agent settings (local-first, single owner).
export function Settings() {
  const [owner, setOwner] = useLocalOwner();
  const [ownerDraft, setOwnerDraft] = useState(owner);
  const [link, setLink] = useState<LinkStatus | null>(null);
  const [health, setHealth] = useState<ConnectorHealth | null>(null);
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const [policy, setPolicy] = useState<SpendPolicy | null>(null);
  const [limitDraft, setLimitDraft] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [copiedMcp, setCopiedMcp] = useState(false);

  const refresh = useCallback(async () => {
    const [nextRuntime, nextHealth, nextPolicy] = await Promise.all([
      api.runtime().catch(() => null),
      api.connectorHealth(owner).catch(() => null),
      api.getPolicy(owner).catch(() => null),
    ]);
    const live = nextRuntime?.live_money_enabled ?? true;
    const nextLink = await (live ? api.linkPreflight(owner) : api.linkStatus(owner)).catch(() => null);
    setLink(nextLink);
    setHealth(nextHealth);
    setRuntime(nextRuntime);
    setPolicy(nextPolicy);
    setLimitDraft(
      nextPolicy?.spend_limit_cents != null
        ? (nextPolicy.spend_limit_cents / 100).toString()
        : ""
    );
  }, [owner]);
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { setOwnerDraft(owner); }, [owner]);

  const connect = async () => {
    setBusy("link");
    try { await api.linkConnect(owner); await refresh(); } finally { setBusy(null); }
  };
  const mint = async () => {
    setBusy("token");
    try {
      const r = await api.mintAgentToken(owner);
      setToken(r.token);
      setCopied(false);
      setHealth(await api.connectorHealth(owner).catch(() => null));
    } finally { setBusy(null); }
  };
  const saveOwner = () => {
    setOwner(ownerDraft);
    setToken(null);
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
  const submitOwner = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    saveOwner();
  };
  const copyToken = async () => {
    if (!token) return;
    try { await navigator.clipboard.writeText(token); setCopied(true); setTimeout(() => setCopied(false), 1800); } catch { /* clipboard blocked */ }
  };
  const copyMcp = async () => {
    if (!health?.mcp.command) return;
    try { await navigator.clipboard.writeText(health.mcp.command); setCopiedMcp(true); setTimeout(() => setCopiedMcp(false), 1800); } catch { /* clipboard blocked */ }
  };
  const liveMoneyEnabled = runtime?.live_money_enabled ?? true;
  const localOnlyFunding = fundingIsLocalOnly(link, liveMoneyEnabled);
  const fundingReady = fundingIsReady(link, liveMoneyEnabled);
  const fundingLabel = fundingDisplay(link, liveMoneyEnabled);
  const workerLabel = health ? `Worker ${health.worker.status}` : "Worker unknown";
  const tokenLabel = health?.agent_token.status === "ready"
    ? `Token ${health.agent_token.token_prefix}`
    : "No agent token";
  const localApi = health?.runtime.base_url ?? "Checking...";
  const ownerChanged = ownerDraft.trim() !== owner;
  const refreshHealth = async () => {
    setBusy("health");
    try { await refresh(); } finally { setBusy(null); }
  };

  return (
    <div className="pg">
      <div className="pg-head">
        <div className="pg-eyebrow m">Account</div>
        <div className="pg-title">Settings</div>
        <div className="pg-lede">Pact is local-first — one owner, your own agent. Connect funding, verify the local API, and copy the MCP command your coach uses.</div>
      </div>

      <div className="set-overview">
        <div className="set-overview-item">
          <span className="m">Owner</span>
          <strong>{owner}</strong>
        </div>
        <div className="set-overview-item">
          <span className="m">Funding</span>
          <strong>{link == null ? "Checking" : fundingReady ? localOnlyFunding ? "Dry run" : "Ready" : "Setup needed"}</strong>
        </div>
        <div className="set-overview-item">
          <span className="m">Agent</span>
          <strong>{health?.agent_token.status === "ready" ? "Token ready" : "Needs token"}</strong>
        </div>
      </div>

      <div className="set-card">
        <div className="set-row">
          <div className="set-row-main">
            <div className="set-k">Owner</div>
            <div className="set-v">This email scopes local pacts, funding, and agent tokens.</div>
          </div>
          <form className="set-owner-form" onSubmit={submitOwner}>
            <input
              aria-label="Owner email"
              className="set-input"
              value={ownerDraft}
              onChange={(e) => setOwnerDraft(e.target.value)}
              onBlur={saveOwner}
              onKeyDown={(e) => { if (e.key === "Enter") saveOwner(); }}
            />
            <button className="set-copy primary" type="submit" disabled={!ownerChanged}>
              Save owner
            </button>
          </form>
        </div>
      </div>

      <div className="set-grid">
        <div className="set-card">
          <div className="set-row">
            <div>
              <div className="set-k">Funding source</div>
              <div className="set-v">
                {link == null ? "Checking..." : fundingReady
                  ? <span className="set-ok">{localOnlyFunding ? fundingLabel : `Connected · ${fundingLabel}`}</span>
                  : `Not connected${link?.error ? ` · ${link.error}` : " — a missed pact can't be charged until you connect."}`}
              </div>
            </div>
            {!fundingReady && (
              <button className="ov-btn sm" onClick={connect} disabled={busy === "link"}>
                {busy === "link" ? "Connecting..." : "Connect Link"}
              </button>
            )}
          </div>
          <div className="set-note m">
            {localOnlyFunding
              ? "No real card is connected in this packaged build. Link is in local dry-run mode, so no money can move."
              : !fundingReady
                ? "Finish Link setup before Pact can charge missed pacts."
              : "Pact never holds your money. Connecting registers the funding source — no donation moves now."}
          </div>
        </div>

        <div className="set-card">
          <div className="set-row">
            <div>
              <div className="set-k">Agent token</div>
              <div className="set-v">Bring your own agent, install the <span className="m">/pact</span> skill, and paste this token to link it to your account.</div>
            </div>
            <button className="ov-btn sm" onClick={mint} disabled={busy === "token"}>
              {busy === "token" ? "..." : token ? "Regenerate" : "Generate token"}
            </button>
          </div>
          {token && (
            <>
              <div className="set-token-row">
                <code className="set-token m">{token}</code>
                <button className="set-copy" aria-label="Copy agent token" onClick={copyToken}>{copied ? "Copied" : "Copy"}</button>
              </div>
              <ol className="set-steps">
                <li>Bring your agent (Hermes is near-built-in; Claude Code = drop the <span className="m">/pact</span> skill file).</li>
                <li>Install the <span className="m">/pact</span> skill.</li>
                <li>Paste this token so it claims your pacts and relays coaching.</li>
              </ol>
            </>
          )}
        </div>
      </div>

      <div className="set-card">
        <div className="set-row">
          <div className="set-row-main">
            <div className="set-k">Agent spend limit</div>
            <div className="set-v">
              The most your agent may donate per missed pact.{" "}
              {policy?.rail === "nemoguard"
                ? "Enforced by NVIDIA NeMo Guardrails before any money moves."
                : "Enforced by the spend policy before any money moves."}
            </div>
          </div>
          <form
            className="set-owner-form"
            onSubmit={(e) => { e.preventDefault(); saveLimit(); }}
          >
            <input
              aria-label="Agent spend limit in dollars"
              className="set-input"
              type="number"
              min="0"
              step="0.01"
              placeholder="No limit"
              value={limitDraft}
              onChange={(e) => setLimitDraft(e.target.value)}
            />
            <button className="set-copy primary" type="submit" disabled={busy === "limit"}>
              {busy === "limit" ? "Saving..." : "Save limit"}
            </button>
          </form>
        </div>
        <div className="set-note m">
          {policy == null
            ? "Checking..."
            : policy.spend_limit_cents == null
              ? "No limit set — your agent can donate up to the per-pact stake cap."
              : `Your agent may spend up to $${(policy.spend_limit_cents / 100).toFixed(2)} per missed pact. ${policy.rail === "nemoguard" ? "NemoGuard" : "The spend policy"} enforces this on every spend.`}
        </div>
      </div>

      <div className="set-card">
        <div className="set-row">
          <div>
            <div className="set-k">Agent connector health</div>
            <div className="set-v">MCP, Claude Code, and Hermes all use the same local Pact engine and owner token.</div>
          </div>
          <button className="ov-btn sm" onClick={refreshHealth} disabled={busy === "health"}>
            {busy === "health" ? "Refreshing..." : "Refresh"}
          </button>
        </div>
        <div className="set-health-strip">
          <span className={`set-badge ${statusClass(health?.agent_token.status ?? "missing")}`}>{tokenLabel}</span>
          <span className={`set-badge ${statusClass(health?.worker.status ?? "offline")}`}>{workerLabel}</span>
          <span className="set-badge muted">{health?.capabilities.vision ? "Vision ready" : "Text only"}</span>
        </div>
        {health && (
          <>
            <div className="set-config-grid">
              <div className="set-config-cell">
                <span className="m">Local API</span>
                <code>{localApi}</code>
              </div>
              <div className="set-config-cell">
                <span className="m">MCP server</span>
                <code>{health.mcp.server_name}</code>
              </div>
            </div>
            <div className="set-conn-list">
              {health.connectors.map((connector) => (
                <ConnectorRow key={connector.key} connector={connector} />
              ))}
            </div>
            <div className="set-command-head">
              <div className="set-note m">MCP command</div>
              <button className="set-copy" aria-label="Copy MCP command" onClick={copyMcp}>{copiedMcp ? "Copied ✓" : "Copy command"}</button>
            </div>
            <code className="set-command m">{health.mcp.command}</code>
          </>
        )}
      </div>
    </div>
  );
}

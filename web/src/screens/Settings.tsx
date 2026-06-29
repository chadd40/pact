import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { fundingDisplay } from "../lib/funding";
import { useLocalOwner } from "../owner";
import type { ConnectorEntry, ConnectorHealth, LinkStatus } from "../types";

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
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [copiedMcp, setCopiedMcp] = useState(false);

  const refresh = useCallback(async () => {
    const [nextLink, nextHealth] = await Promise.all([
      api.linkStatus(owner).catch(() => null),
      api.connectorHealth(owner).catch(() => null),
    ]);
    setLink(nextLink);
    setHealth(nextHealth);
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
  const copyToken = async () => {
    if (!token) return;
    try { await navigator.clipboard.writeText(token); setCopied(true); setTimeout(() => setCopied(false), 1800); } catch { /* clipboard blocked */ }
  };
  const copyMcp = async () => {
    if (!health?.mcp.command) return;
    try { await navigator.clipboard.writeText(health.mcp.command); setCopiedMcp(true); setTimeout(() => setCopiedMcp(false), 1800); } catch { /* clipboard blocked */ }
  };
  const fundingLabel = fundingDisplay(link);
  const workerLabel = health ? `Worker ${health.worker.status}` : "Worker unknown";
  const tokenLabel = health?.agent_token.status === "ready"
    ? `Token ${health.agent_token.token_prefix}`
    : "No agent token";

  return (
    <div className="pg">
      <div className="pg-head">
        <div className="pg-eyebrow m">Account</div>
        <div className="pg-title">Settings</div>
        <div className="pg-lede">Pact is local-first — one owner, your own agent. Connect a funding source so a missed pact can actually be charged, and link your agent so it can coach you.</div>
      </div>

      <div className="set-card">
        <div className="set-row">
          <div>
            <div className="set-k">Owner</div>
            <input
              className="set-input"
              value={ownerDraft}
              onChange={(e) => setOwnerDraft(e.target.value)}
              onBlur={saveOwner}
              onKeyDown={(e) => { if (e.key === "Enter") saveOwner(); }}
            />
          </div>
        </div>
      </div>

      <div className="set-card">
        <div className="set-row">
          <div>
            <div className="set-k">Funding source (Link)</div>
            <div className="set-v">
              {link == null ? "—" : link.connected
                ? <span className="set-ok">Connected · {fundingLabel}</span>
                : `Not connected${link?.error ? ` · ${link.error}` : " — a missed pact can't be charged until you connect."}`}
            </div>
          </div>
          {!link?.connected && (
            <button className="ov-btn sm" onClick={connect} disabled={busy === "link"}>
              {busy === "link" ? "Connecting…" : "Connect Link"}
            </button>
          )}
        </div>
        <div className="set-note m">Pact never holds your money. Connecting registers the funding source — no donation moves now.</div>
      </div>

      <div className="set-card">
        <div className="set-row">
          <div>
            <div className="set-k">Your agent</div>
            <div className="set-v">Bring your own agent, install the <span className="m">/pact</span> skill, and paste this token to link it to your account.</div>
          </div>
          <button className="ov-btn sm" onClick={mint} disabled={busy === "token"}>
            {busy === "token" ? "…" : token ? "Regenerate" : "Generate token"}
          </button>
        </div>
        {token && (
          <>
            <div className="set-token-row">
              <code className="set-token m">{token}</code>
              <button className="set-copy" aria-label="Copy agent token" onClick={copyToken}>{copied ? "Copied ✓" : "Copy"}</button>
            </div>
            <ol className="set-steps">
              <li>Bring your agent (Hermes is near-built-in; Claude Code = drop the <span className="m">/pact</span> skill file).</li>
              <li>Install the <span className="m">/pact</span> skill.</li>
              <li>Paste this token so it claims your pacts and relays coaching.</li>
            </ol>
          </>
        )}
      </div>

      <div className="set-card">
        <div className="set-row">
          <div>
            <div className="set-k">Agent connector health</div>
            <div className="set-v">MCP, Claude Code, and Hermes all use the same local Pact engine and owner token.</div>
          </div>
          <button className="ov-btn sm" onClick={refresh} disabled={busy === "health"}>
            Refresh
          </button>
        </div>
        <div className="set-health-strip">
          <span className={`set-badge ${statusClass(health?.agent_token.status ?? "missing")}`}>{tokenLabel}</span>
          <span className={`set-badge ${statusClass(health?.worker.status ?? "offline")}`}>{workerLabel}</span>
          <span className="set-badge muted">MCP server {health?.mcp.server_name ?? "pact"}</span>
        </div>
        {health && (
          <>
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

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useDemo } from "../App";
import { useAppData } from "../data";
import { useLocalOwner } from "../owner";
import { GoalGlyph } from "../components/GoalGlyph";
import { ChatShell, StatusPill, type ChatMessage } from "../components/ChatShell";
import { formatDateTime } from "../lib";
import { AGENTS } from "./Create";
import type { CoachingMessage, ConnectorHealth } from "../types";

// Global coach view: your agent + the recent nudges across all your pacts.
export function Coach() {
  const { bump } = useDemo();
  const { pacts } = useAppData();
  const [owner] = useLocalOwner();
  const navigate = useNavigate();
  const [feed, setFeed] = useState<CoachingMessage[]>([]);
  const [health, setHealth] = useState<ConnectorHealth | null>(null);
  const [copiedMcp, setCopiedMcp] = useState(false);

  // Pacts come from shared AppData; only the outbox feed is Coach-specific.
  useEffect(() => {
    let alive = true;
    api.outbox(owner)
      .then((out) => alive && setFeed(out.slice().reverse()))
      .catch(() => {});
    api.connectorHealth(owner)
      .then((next) => alive && setHealth(next))
      .catch(() => {});
    return () => { alive = false; };
  }, [bump, owner]);

  const byId = Object.fromEntries(pacts.map((p) => [p.id, p]));
  const coached = pacts.filter((p) => p.status === "active" || p.status === "evaluating" || p.status === "needs_review");
  const hermes = AGENTS[0];
  const workerOnline = health?.worker.status === "online";
  const tokenReady = health?.agent_token.status === "ready";
  const mcpReady = health?.connectors.some((c) => c.key === "mcp" && c.status === "ready") ?? false;
  const mcpCommand = health?.mcp.command ?? "";
  const localApi = health?.runtime.base_url ?? "";
  const copyMcp = async () => {
    if (!mcpCommand) return;
    try {
      await navigator.clipboard.writeText(mcpCommand);
      setCopiedMcp(true);
      setTimeout(() => setCopiedMcp(false), 1800);
    } catch {
      /* clipboard may be unavailable in hardened contexts */
    }
  };
  const consoleRows: ChatMessage[] = feed.length
    ? feed.map((m) => {
      const p = byId[m.pact_id];
      return {
        id: m.id,
        role: m.direction === "inbound" ? "user" : "agent",
        meta: p ? `${p.title} · ${formatDateTime(m.sent_at)}` : formatDateTime(m.sent_at),
        body: m.body,
        actions: p ? (
          <button className="coach-chat-action" onClick={() => navigate(`/pact/${m.pact_id}`)} aria-label={`Open chat for ${p.title}`}>
            Open chat
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><path d="M9 6l6 6-6 6" /></svg>
          </button>
        ) : null,
      };
    })
    : [{
      id: "empty",
      role: "agent",
      body: "No nudges waiting. When a pact needs attention, it will land here as a coaching thread.",
    }];

  return (
    <div className="pg">
      <div className="pg-head">
        <div className="pg-eyebrow m">Your agent</div>
        <div className="pg-title">Coach</div>
        <div className="pg-lede">Hermes keeps the live thread across your pacts: setup health, recent nudges, and a fast path back into each chat.</div>
      </div>

      <div className="coach-console">
        <aside className="coach-agent-panel" aria-label="Hermes coach profile">
          <div className="coach-agent-lockup">
            <div className="coach-hero-av">{hermes.avatar ? <img src={hermes.avatar} alt="" /> : null}</div>
            <div>
              <div className="coach-hero-name">Hermes</div>
              <div className="coach-hero-sub"><span className="dot" />{workerOnline ? "Live worker online" : "Worker waiting"}</div>
            </div>
          </div>

          <div className="coach-setup-list">
            <div className="coach-setup-row">
              <span className="coach-status-k m">Agent token</span>
              <StatusPill tone={tokenReady ? "ok" : "warn"}>{tokenReady ? health?.agent_token.token_prefix ?? "ready" : "missing"}</StatusPill>
            </div>
            <div className="coach-setup-row">
              <span className="coach-status-k m">MCP</span>
              <StatusPill tone={mcpReady ? "ok" : "warn"}>{mcpReady ? "ready" : "needs setup"}</StatusPill>
            </div>
            <div className="coach-setup-row">
              <span className="coach-status-k m">Vision</span>
              <StatusPill tone={health?.capabilities.vision ? "ok" : "warn"}>{health?.capabilities.vision ? "ready" : "waiting"}</StatusPill>
            </div>
          </div>

          {mcpCommand && (
            <div className="coach-command-block">
              <div className="coach-command-head">
                <div>
                  <div className="coach-status-k m">MCP configuration</div>
                  {localApi && (
                    <div className="coach-local-api">
                      <span>Local API</span>
                      <code>{localApi}</code>
                    </div>
                  )}
                </div>
                <button className="coach-copy" aria-label="Copy MCP command" onClick={copyMcp}>
                  {copiedMcp ? "Copied" : "Copy"}
                </button>
              </div>
              <code className="coach-command m">{mcpCommand}</code>
            </div>
          )}

          <div className="coach-side-section">
            <div className="coach-side-head m">Live pacts · {coached.length}</div>
            {coached.length === 0 ? (
              <div className="coach-side-empty">No live pacts right now.</div>
            ) : (
              <div className="coach-pacts">
                {coached.map((p) => (
                  <button key={p.id} className="coach-pact-row" onClick={() => navigate(`/pact/${p.id}`)} aria-label={`Open pact ${p.title}`}>
                    <span className="coach-pact-glyph"><GoalGlyph title={p.title} size={18} /></span>
                    <span className="coach-pact-name">{p.title}</span>
                    <span className="coach-pact-open">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><path d="M9 6l6 6-6 6" /></svg>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </aside>

        <section className="coach-thread-panel" aria-label="Recent coach messages">
          <ChatShell
            label="Hermes coach console"
            agentName="Hermes"
            agentAvatar={hermes.avatar}
            messages={consoleRows}
          />
        </section>
      </div>
    </div>
  );
}

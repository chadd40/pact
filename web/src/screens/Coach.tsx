import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useDemo } from "../App";
import { useAppData } from "../data";
import { useLocalOwner } from "../owner";
import { GoalGlyph } from "../components/GoalGlyph";
import { StatusPill } from "../components/ChatShell";
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

  return (
    <div className="pg">
      <div className="pg-head">
        <div className="pg-eyebrow m">Your agent</div>
        <div className="pg-title">Coach</div>
        <div className="pg-lede">Hermes is watching every live pact — nudging you toward your stake and judging your proof. Open any pact to talk.</div>
      </div>

      <div className="coach-hero">
        <div className="coach-hero-av">{hermes.avatar ? <img src={hermes.avatar} alt="" /> : null}</div>
        <div className="coach-hero-body">
          <div className="coach-hero-name">Hermes</div>
          <div className="coach-hero-sub"><span className="dot" />{workerOnline ? "Live worker online" : "Worker waiting"} · coaching {coached.length} pact{coached.length === 1 ? "" : "s"}</div>
        </div>
      </div>

      <div className="coach-status-grid">
        <div className="coach-status-card">
          <div className="coach-status-k m">Agent token</div>
          <StatusPill tone={tokenReady ? "ok" : "warn"}>{tokenReady ? health?.agent_token.token_prefix ?? "ready" : "missing"}</StatusPill>
        </div>
        <div className="coach-status-card">
          <div className="coach-status-k m">MCP</div>
          <StatusPill tone={mcpReady ? "ok" : "warn"}>{mcpReady ? "ready" : "needs setup"}</StatusPill>
        </div>
        <div className="coach-status-card">
          <div className="coach-status-k m">Capabilities</div>
          <StatusPill tone={health?.capabilities.vision ? "ok" : "warn"}>{health?.capabilities.vision ? "text + vision" : "waiting"}</StatusPill>
        </div>
      </div>
      {health?.mcp.command && <code className="coach-command m">{health.mcp.command}</code>}

      <div className="pg-section-label m">Recent from your coach</div>
      {feed.length === 0 ? (
        <div className="pg-empty">No nudges waiting. You're all caught up.</div>
      ) : (
        <div className="coach-feed">
          {feed.map((m) => {
            const p = byId[m.pact_id];
            return (
              <button key={m.id} className="coach-feed-row" onClick={() => navigate(`/pact/${m.pact_id}`)}>
                <span className="coach-feed-glyph">{p ? <GoalGlyph title={p.title} size={18} /> : null}</span>
                <span className="coach-feed-main">
                  <span className="coach-feed-pact">{p?.title ?? "Pact"}</span>
                  <span className="coach-feed-body">{m.body}</span>
                </span>
                <span className="coach-feed-when m">{formatDateTime(m.sent_at)}</span>
              </button>
            );
          })}
        </div>
      )}

      <div className="pg-section-label m">Live pacts</div>
      {coached.length === 0 ? (
        <div className="pg-empty">No live pacts right now.</div>
      ) : (
        <div className="coach-pacts">
          {coached.map((p) => (
            <button key={p.id} className="coach-pact-row" onClick={() => navigate(`/pact/${p.id}`)}>
              <span className="coach-pact-glyph"><GoalGlyph title={p.title} size={18} /></span>
              <span className="coach-pact-name">{p.title}</span>
              <span className="coach-pact-open">Open chat
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><path d="M9 6l6 6-6 6" /></svg>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

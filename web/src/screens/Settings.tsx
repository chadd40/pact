import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { fundingDisplay, fundingIsLocalOnly, fundingIsReady, paymentMethodLabel } from "../lib/funding";
import { useLocalDisplayName, useLocalOwner } from "../owner";
import type { ConnectorHealth, LinkStatus, RuntimeInfo, SpendPolicy } from "../types";
import { RewindIcon, TokenIcon } from "./agentIcons";
import "./onboard.css";

// The local Pact API the agent's `pact serve` command connects back to. Shared
// with Onboard (same localStorage key) so a URL set in either place persists.
const AGENT_BASE_URL_KEY = "pact.agentBaseUrl";
const DEFAULT_AGENT_BASE_URL = "http://127.0.0.1:8000";

function statusClass(status: string): string {
  if (["ready", "online", "installed"].includes(status)) return "ok";
  if (["missing", "needs_token", "needs_install", "offline"].includes(status)) return "warn";
  return "muted";
}

// Account settings — local-first, single owner. Deliberately lean: the only
// things Pact itself manages are your name, the Link funding connection, the
// agent hookup, and the NemoGuard spend limit. Cardholder name and billing
// address ride with the Link card credential, so Pact never collects them; the
// owner id (email) stays an internal scoping key and is not shown.
export function Settings() {
  const [owner] = useLocalOwner();
  const [displayName, setDisplayName] = useLocalDisplayName();
  const [nameDraft, setNameDraft] = useState(displayName);
  const [link, setLink] = useState<LinkStatus | null>(null);
  const [health, setHealth] = useState<ConnectorHealth | null>(null);
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const [policy, setPolicy] = useState<SpendPolicy | null>(null);
  const [limitDraft, setLimitDraft] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [copiedServe, setCopiedServe] = useState(false);
  const [copiedMcp, setCopiedMcp] = useState(false);
  const [agentBaseUrl, setAgentBaseUrl] = useState(() =>
    window.localStorage.getItem(AGENT_BASE_URL_KEY) ?? ""
  );

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
  useEffect(() => { setNameDraft(displayName); }, [displayName]);

  // Keep the URL field pointed at the live local API until the user overrides it.
  useEffect(() => {
    if (!agentBaseUrl && health?.runtime.base_url) setAgentBaseUrl(health.runtime.base_url);
  }, [agentBaseUrl, health?.runtime.base_url]);
  useEffect(() => {
    if (agentBaseUrl.trim()) window.localStorage.setItem(AGENT_BASE_URL_KEY, agentBaseUrl.trim());
  }, [agentBaseUrl]);

  // "Your name" is the name the owner signs pacts with. If they've never set one
  // explicitly, adopt the signer name from a pact they already sealed so the
  // field is filled in without re-typing (their instinct: keep the name after
  // the first pact). Only seeds when empty, so it never fights a manual edit.
  useEffect(() => {
    if (displayName.trim()) return;
    let cancelled = false;
    api.listPacts(owner)
      .then((pacts) => {
        if (cancelled) return;
        const seed = pacts.map((p) => p.signer_name?.trim()).find(Boolean);
        if (seed) setDisplayName(seed);
      })
      .catch(() => { /* no pacts yet is fine */ });
    return () => { cancelled = true; };
  }, [owner, displayName, setDisplayName]);

  const shownName = displayName.trim() || owner;
  const nameChanged = nameDraft.trim() !== displayName;
  const saveName = () => setDisplayName(nameDraft);

  const connect = async () => {
    setBusy("link");
    try { await api.linkConnect(owner); await refresh(); } finally { setBusy(null); }
  };
  const mint = async () => {
    setBusy("token");
    try {
      const r = await api.mintAgentToken(owner);
      setToken(r.token);
      setHealth(await api.connectorHealth(owner).catch(() => null));
    } finally { setBusy(null); }
  };
  const recheck = async () => {
    setBusy("recheck");
    try { await refresh(); } finally { setBusy(null); }
  };
  const saveLimit = async () => {
    const trimmed = limitDraft.trim();
    const cents = trimmed === "" ? null : Math.round(parseFloat(trimmed) * 100);
    if (cents !== null && (Number.isNaN(cents) || cents < 0)) return;
    setBusy("limit");
    try {
      const next = await api.setPolicy(owner, cents);
      setPolicy(next);
      setLimitDraft(next.spend_limit_cents != null ? (next.spend_limit_cents / 100).toString() : "");
    } finally { setBusy(null); }
  };

  const liveMoneyEnabled = runtime?.live_money_enabled ?? true;
  const localOnlyFunding = fundingIsLocalOnly(link, liveMoneyEnabled);
  const fundingReady = fundingIsReady(link, liveMoneyEnabled);
  const fundingLabel = fundingDisplay(link, liveMoneyEnabled);
  const cardLabel = link?.payment_method_last4 ? paymentMethodLabel(link) : null;

  const agentDone = !!token || health?.agent_token.status === "ready";
  const workerStatus = health?.worker.status ?? "offline";
  const serveBaseUrl = (agentBaseUrl || health?.runtime.base_url || DEFAULT_AGENT_BASE_URL).trim();
  const commandToken = token ?? "<paste your token>";
  const serveCommand = `pact serve --base-url ${serveBaseUrl} --agent-token ${commandToken}`;
  useEffect(() => { setCopiedServe(false); }, [serveCommand]);

  const copyServe = async () => {
    try { await navigator.clipboard.writeText(serveCommand); setCopiedServe(true); setTimeout(() => setCopiedServe(false), 1800); } catch { /* clipboard blocked */ }
  };
  const copyMcp = async () => {
    if (!health?.mcp.command) return;
    try { await navigator.clipboard.writeText(health.mcp.command); setCopiedMcp(true); setTimeout(() => setCopiedMcp(false), 1800); } catch { /* clipboard blocked */ }
  };

  return (
    <div className="pg">
      <div className="pg-head">
        <div className="pg-eyebrow m">Account</div>
        <div className="pg-title">Settings</div>
        <div className="pg-lede">Pact is local-first — one owner, your own agent. Set your name, connect Link, hook up your agent, and cap what it can donate.</div>
      </div>

      <div className="set-overview">
        <div className="set-overview-item">
          <span className="m">You</span>
          <strong>{shownName}</strong>
        </div>
        <div className="set-overview-item">
          <span className="m">Link</span>
          <strong>{link == null ? "Checking" : fundingReady ? localOnlyFunding ? "Dry run" : "Ready" : "Setup needed"}</strong>
        </div>
        <div className="set-overview-item">
          <span className="m">Agent</span>
          <strong>{agentDone ? "Ready" : "Needs token"}</strong>
        </div>
      </div>

      {/* ── You ─────────────────────────────────────────────────────────────── */}
      <div className="set-card">
        <div className="set-row">
          <div className="set-row-main">
            <div className="set-k">Your name</div>
            <div className="set-v">The name you sign pacts with. It shows on your card and pre-fills the next pact you make.</div>
          </div>
          <form className="set-owner-form" onSubmit={(e) => { e.preventDefault(); saveName(); }}>
            <input
              aria-label="Your name"
              className="set-input"
              value={nameDraft}
              placeholder="Your name"
              onChange={(e) => setNameDraft(e.target.value)}
              onBlur={saveName}
              onKeyDown={(e) => { if (e.key === "Enter") saveName(); }}
            />
            <button className="set-copy primary" type="submit" disabled={!nameChanged}>
              Save name
            </button>
          </form>
        </div>
      </div>

      {/* ── Link ────────────────────────────────────────────────────────────── */}
      <div className="set-card">
        <div className="set-row">
          <div className="set-row-main">
            <div className="set-k">Link</div>
            <div className="set-v">
              {link == null ? "Checking..." : fundingReady
                ? <span className="set-ok">{localOnlyFunding ? fundingLabel : cardLabel ? `Connected · ${cardLabel}` : `Connected · ${fundingLabel}`}</span>
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
              : "Your name and billing address travel with the Link card credential, so Pact never stores them. Pact never holds your money either."}
        </div>
      </div>

      {/* ── Your agent (onboard-style connect) ──────────────────────────────── */}
      <div className="onb-card">
        <div className="onb-row">
          <div className="onb-row-main">
            <h2 className="onb-k">Your agent</h2>
            <div className="onb-v">
              {agentDone
                ? "Run this in your agent so it can act on your pacts, claim tasks, coach you, and pay a missed donation."
                : "Generate a token and run this in your agent so it can act on your pacts, claim tasks, coach you, and pay a missed donation."}
            </div>
          </div>
        </div>
        <label className="onb-field">
          <span className="onb-field-label">Local Pact API URL</span>
          <input
            className="onb-input"
            aria-label="Local Pact API URL"
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
            className={`onb-copy${copiedServe ? " is-copied" : ""}`}
            aria-label={copiedServe ? "Serve command copied" : "Copy serve command"}
            onClick={copyServe}
          >
            {copiedServe ? "Copied" : "Copy command"}
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
            Token {health?.agent_token.token_prefix ?? "ready"} · worker {workerStatus === "online" ? "serving" : "not serving yet"}
          </div>
        )}
        {health && (
          <>
            <div className="set-health-strip">
              <span className={`set-badge ${statusClass(health.agent_token.status)}`}>
                {health.agent_token.status === "ready" ? `Token ${health.agent_token.token_prefix}` : "No agent token"}
              </span>
              <span className={`set-badge ${statusClass(health.worker.status)}`}>Worker {health.worker.status}</span>
              <span className="set-badge muted">{health.capabilities.vision ? "Vision ready" : "Text only"}</span>
            </div>
            <div className="set-command-head">
              <div className="set-note m">MCP server command</div>
              <button className="set-copy" aria-label="Copy MCP command" onClick={copyMcp}>{copiedMcp ? "Copied ✓" : "Copy command"}</button>
            </div>
            <code className="set-command m">{health.mcp.command}</code>
          </>
        )}
      </div>

      {/* ── Agent spend limit (NemoGuard) ───────────────────────────────────── */}
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
          <form className="set-owner-form" onSubmit={(e) => { e.preventDefault(); saveLimit(); }}>
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
              : `Your agent may spend up to $${(policy.spend_limit_cents / 100).toFixed(2)} per missed pact. ${policy.rail === "nemoguard" ? "NemoGuard" : "A spend rail modeled on NVIDIA NeMo Guardrails"} enforces this on every spend.`}
        </div>
      </div>
    </div>
  );
}

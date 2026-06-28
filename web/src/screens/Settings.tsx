import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useLocalOwner } from "../owner";
import type { LinkStatus } from "../types";

// Account / funding / agent settings (local-first, single owner).
export function Settings() {
  const [owner, setOwner] = useLocalOwner();
  const [ownerDraft, setOwnerDraft] = useState(owner);
  const [link, setLink] = useState<LinkStatus | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const refresh = useCallback(async () => {
    setLink(await api.linkStatus(owner).catch(() => null));
  }, [owner]);
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { setOwnerDraft(owner); }, [owner]);

  const connect = async () => {
    setBusy("link");
    try { await api.linkConnect(owner); await refresh(); } finally { setBusy(null); }
  };
  const mint = async () => {
    setBusy("token");
    try { const r = await api.mintAgentToken(owner); setToken(r.token); setCopied(false); } finally { setBusy(null); }
  };
  const saveOwner = () => {
    setOwner(ownerDraft);
    setToken(null);
  };
  const copyToken = async () => {
    if (!token) return;
    try { await navigator.clipboard.writeText(token); setCopied(true); setTimeout(() => setCopied(false), 1800); } catch { /* clipboard blocked */ }
  };
  const fundingLabel = link?.payment_method_last4
    ? `${link.payment_method_label ?? "Card"} •••• ${link.payment_method_last4}`
    : link?.funding_ref;

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
              <button className="set-copy" onClick={copyToken}>{copied ? "Copied ✓" : "Copy"}</button>
            </div>
            <ol className="set-steps">
              <li>Bring your agent (Hermes is near-built-in; Claude Code = drop the <span className="m">/pact</span> skill file).</li>
              <li>Install the <span className="m">/pact</span> skill.</li>
              <li>Paste this token so it claims your pacts and relays coaching.</li>
            </ol>
          </>
        )}
      </div>

      <div className="set-card muted-card">
        <div className="set-k">Demo</div>
        <div className="set-note m">This build runs on a demo clock with seeded pacts. Use the “States” menu (bottom-left) to seed, advance the clock, and jump to any pact state.</div>
      </div>
    </div>
  );
}

import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, DEMO_OWNER } from "../api";
import { useDemo } from "../App";
import { CoachThread } from "../components/CoachThread";
import { LinkConnect } from "../components/LinkConnect";
import { ProgressRing } from "../components/ProgressRing";
import { dollars, formatDate } from "../lib";
import type { Charity, CoachingMessage, LinkStatus, Pact, Packet, Proof } from "../types";

const LIVE = new Set<string>(["active", "evaluating"]);
const KEPT = new Set<string>(["succeeded", "canceled_release"]);

export function PactView() {
  const { pactId } = useParams();
  const { nowMs, signalChange } = useDemo();
  const navigate = useNavigate();

  const [pact, setPact] = useState<Pact | null>(null);
  const [proofs, setProofs] = useState<Proof[]>([]);
  const [coach, setCoach] = useState<CoachingMessage[]>([]);
  const [packet, setPacket] = useState<Packet | null>(null);
  const [charity, setCharity] = useState<Charity | null>(null);
  const [link, setLink] = useState<LinkStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    if (!pactId) return;
    const p = await api.getPact(pactId).catch(() => null);
    if (!p) {
      setErr("Pact not found.");
      return;
    }
    setPact(p);
    const [ps, cs, cats, ls] = await Promise.all([
      api.getProofs(pactId).catch(() => [] as Proof[]),
      api.getCoach(pactId).catch(() => [] as CoachingMessage[]),
      api.charities().catch(() => [] as Charity[]),
      api.linkStatus(DEMO_OWNER).catch(() => null),
    ]);
    setProofs(ps);
    setCoach(cs);
    setLink(ls);
    setCharity(cats.find((c) => c.id === p.charity_id) ?? null);
    if (!LIVE.has(p.status) && p.status !== "needs_review") {
      setPacket(await api.packet(pactId).catch(() => null));
    }
  }, [pactId]);

  useEffect(() => {
    load();
  }, [load, nowMs]);

  const onPickFile = () => fileRef.current?.click();

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || !pact) return;
    setBusy("proof");
    setErr(null);
    try {
      const { token } = await api.proofToken(pact.id);
      await api.uploadProofImage(pact.id, token, file, true);
      await load();
      signalChange();
    } catch {
      setErr("Couldn't submit that proof. Try again.");
    } finally {
      setBusy(null);
    }
  };

  const sendCoach = async (text: string) => {
    if (!pact) return;
    await api.postCoach(pact.id, text).catch(() => {});
    setCoach(await api.getCoach(pact.id).catch(() => coach));
  };

  const act = async (kind: string, fn: () => Promise<unknown>) => {
    setBusy(kind);
    setErr(null);
    try {
      await fn();
      await load();
      signalChange();
    } catch {
      setErr("That didn't go through. Try again.");
    } finally {
      setBusy(null);
    }
  };

  if (err && !pact) {
    return (
      <div className="pv">
        <div className="pv-note">{err}</div>
        <button className="pc-btn" onClick={() => navigate("/dashboard")}>Back to dashboard</button>
      </div>
    );
  }
  if (!pact) return <div className="pv"><div className="pv-note">Loading…</div></div>;

  const prog = pact.progress;
  const live = LIVE.has(pact.status);
  const review = pact.status === "needs_review";
  const kept = KEPT.has(pact.status);
  const windowOpen =
    !pact.dispute_window_closes_at ||
    new Date(pact.dispute_window_closes_at).getTime() > nowMs;
  const canDispute = pact.status === "failed" && windowOpen;
  const linkRequired = pact.status === "donation_pending" && link != null && !link.connected;

  return (
    <div className="pv">
      <input ref={fileRef} type="file" accept="image/*" hidden onChange={onFile} />

      <button className="pv-back m" onClick={() => navigate("/dashboard")}>← Dashboard</button>

      {/* Header */}
      <div className="pv-head">
        {charity && <img className="pv-stamp" src={charity.stamp} alt={charity.name} />}
        <div>
          <div className="pv-title">{pact.title}</div>
          <div className="pv-sub m">
            {dollars(pact.stake_amount_cents)} on the line · {pact.target_count}× · due{" "}
            {formatDate(pact.deadline_at)}
            {charity && <> · {charity.name}</>}
          </div>
        </div>
      </div>

      {err && <div className="pv-err">{err}</div>}

      {/* LIVE: progress + proof + coaching */}
      {live && (
        <>
          <div className="pv-progress card">
            <ProgressRing
              pct={prog?.pct ?? 0}
              size={150}
              stroke={12}
              tone={prog?.behind ? "muted" : "gold"}
              label={`${prog?.valid_count ?? 0}/${prog?.target ?? pact.target_count}`}
              sub="check-ins"
            />
            <div className="pv-progress-side">
              <div className={`pv-pace ${prog?.behind ? "behind" : "ontrack"}`}>
                {prog?.behind ? "Behind pace" : "On track"}
              </div>
              <div className="pv-days m">
                {(prog?.days_left ?? 0) === 0
                  ? "Deadline reached"
                  : `${prog?.days_left} day${prog?.days_left === 1 ? "" : "s"} left`}
              </div>
              {prog && prog.milestone > 0 && prog.milestone < 100 && (
                <div className="pv-milestone">🎉 {prog.milestone}% there — keep going.</div>
              )}
              {prog?.behind && (
                <div className="pv-loss">
                  {dollars(pact.stake_amount_cents)} and {charity?.name ?? "your charity"} are
                  one missed day away.
                </div>
              )}
            </div>
          </div>

          <div className="pv-proof card">
            <div className="pv-card-title">Prove it</div>
            <button className="pc-btn" onClick={onPickFile} disabled={busy === "proof"}>
              {busy === "proof" ? "Submitting…" : "Add photo proof"}
            </button>
            <div className="pv-proof-list">
              {proofs.length === 0 ? (
                <span className="pv-muted">No proof yet.</span>
              ) : (
                proofs.map((p) => (
                  <span key={p.id} className={`pv-proof-chip pv-proof-${p.status}`}>
                    {p.day_bucket} · {p.status}
                  </span>
                ))
              )}
            </div>
          </div>

          {link != null && !link.connected && (
            <LinkConnect owner={DEMO_OWNER} onConnected={load} variant="prompt" />
          )}

          <div className="pv-coach card">
            <div className="pv-card-title">Coaching</div>
            <CoachThread messages={coach} onSend={sendCoach} agentName={pact.agent ?? "Hermes"} />
          </div>

          <button
            className="pc-btn ghost pv-cancel"
            disabled={busy === "cancel"}
            onClick={() => act("cancel", () => api.cancel(pact.id))}
          >
            {busy === "cancel" ? "…" : "Cancel pact"}
          </button>
          <div className="pv-fine m">
            Cancelling inside the cooling-off window releases your stake. After that it
            forfeits to {charity?.name ?? "your charity"}.
          </div>
        </>
      )}

      {/* REVIEW */}
      {review && (
        <div className="pv-verdict card review">
          <div className="pv-verdict-stamp review">Under review</div>
          <div className="pv-verdict-summary">
            Your proof is being reviewed. No money has moved. Your agent will follow up.
          </div>
          <div className="pv-coach card">
            <CoachThread messages={coach} onSend={sendCoach} agentName={pact.agent ?? "Hermes"} />
          </div>
        </div>
      )}

      {/* VERDICT (terminal / failed / donation states) */}
      {!live && !review && (
        <div className={`pv-verdict card ${kept ? "kept" : "failed"}`}>
          <div className={`pv-verdict-stamp ${kept ? "kept" : "failed"}`}>
            {kept ? "Kept" : "Forfeited"}
          </div>
          <div className="pv-verdict-summary">
            {packet?.verdict?.summary ||
              (kept ? "You kept your word." : "You came up short on this one.")}
          </div>
          {packet?.verdict && (
            <div className="pv-verdict-count m">
              {packet.verdict.valid_proof_count} of {packet.verdict.target_count} verified
            </div>
          )}

          {pact.status === "donation_pending" ? (
            <div className="pv-linkreq">
              <div className="pv-linkreq-title">Resolve your donation</div>
              <div className="pv-linkreq-text">
                You missed, so {dollars(pact.stake_amount_cents)} is owed to{" "}
                {charity?.name ?? "your charity"}.{" "}
                {linkRequired
                  ? "Connect Link and approve it, or decline."
                  : "Approve it in your Link app, or decline."}{" "}
                It stays here until you resolve it.
              </div>
              <div className="pv-linkreq-actions">
                <button
                  className="pc-btn"
                  disabled={busy === "link"}
                  onClick={() =>
                    act("link", async () => {
                      if (linkRequired) await api.linkConnect(DEMO_OWNER);
                      await api.settle(pact.id);
                    })
                  }
                >
                  {busy === "link"
                    ? "…"
                    : linkRequired
                    ? "Connect Link & approve"
                    : "Approve donation"}
                </button>
                <button
                  className="pc-btn ghost"
                  disabled={busy === "decline"}
                  onClick={() => act("decline", () => api.decline(pact.id))}
                >
                  {busy === "decline" ? "…" : "Decline"}
                </button>
              </div>
            </div>
          ) : (
            !kept &&
            pact.status === "donated" && (
              <div className="pv-donation m">
                Donated {dollars(pact.stake_amount_cents)} to {charity?.name ?? "charity"}.
              </div>
            )
          )}

          {canDispute && (
            <div className="pv-dispute">
              <div className="pv-dispute-text">
                Think this is wrong? Submit one more proof — if it clears the target, the
                verdict overturns. One window only.
              </div>
              <button className="pc-btn" onClick={onPickFile} disabled={busy === "proof"}>
                {busy === "proof" ? "Submitting…" : "Add proof to dispute"}
              </button>
              <button
                className="pc-btn ghost"
                disabled={busy === "dispute"}
                onClick={() => act("dispute", () => api.dispute(pact.id))}
              >
                {busy === "dispute" ? "…" : "Re-run verdict"}
              </button>
            </div>
          )}

          <button className="pc-btn ghost" onClick={() => navigate("/dashboard")}>
            Back to dashboard
          </button>
        </div>
      )}
    </div>
  );
}

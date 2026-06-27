import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useClock, useDemo } from "../App";
import { useAppData } from "../data";
import { SubmitSheet } from "../components/SubmitSheet";
import { CoachPane } from "../components/CoachPane";
import { LinkModal } from "../components/LinkModal";
import { DeclineModal } from "../components/DeclineModal";
import { GoalGlyph } from "../components/GoalGlyph";
import { dollars, formatDate, pactNo } from "../lib";
import type { CoachingMessage, Pact, Packet } from "../types";

const LIVE = new Set(["active", "evaluating"]);
const KEPT = new Set(["succeeded", "canceled_release"]);
const DONATED = new Set(["donated", "donation_failed"]);
const DECLINED = new Set(["donation_declined", "canceled_forfeit"]);

export function PactDetail() {
  const { pactId } = useParams();
  const { bump, signalChange } = useDemo();
  const nowMs = useClock();
  const { charityById } = useAppData();
  const navigate = useNavigate();

  const [pact, setPact] = useState<Pact | null>(null);
  const [coach, setCoach] = useState<CoachingMessage[]>([]);
  const [packet, setPacket] = useState<Packet | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const [sheetOpen, setSheetOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [linkOpen, setLinkOpen] = useState(false);
  const [declineOpen, setDeclineOpen] = useState(false);

  const load = useCallback(async () => {
    if (!pactId) return;
    const p = await api.getPact(pactId).catch(() => null);
    if (!p) { setErr("Pact not found."); return; }
    setPact(p);
    setCoach(await api.getCoach(pactId).catch(() => [] as CoachingMessage[]));
    if (!LIVE.has(p.status) && p.status !== "needs_review") {
      setPacket(await api.packet(pactId).catch(() => null));
    }
  }, [pactId]);

  // Refetch on mount, pact change, and explicit data signals (demo advance,
  // actions, overlay resolutions) — NOT on every 1Hz nowMs tick. nowMs stays for
  // the live dispute-window countdown in render only.
  useEffect(() => { load(); }, [load, bump]);

  const sendCoach = async (text: string) => {
    if (!pact) return;
    await api.postCoach(pact.id, text).catch(() => {});
    setCoach(await api.getCoach(pact.id).catch(() => coach));
  };

  const act = async (kind: string, fn: () => Promise<unknown>) => {
    setBusy(kind); setErr(null);
    try { await fn(); await load(); signalChange(); }
    catch { setErr("That didn't go through. Try again."); }
    finally { setBusy(null); }
  };

  if (err && !pact) {
    return (
      <div className="pd-missing">
        <div>{err}</div>
        <button className="pd-btn" onClick={() => navigate("/dashboard")}>Back to home</button>
      </div>
    );
  }
  if (!pact) return <div className="pd-missing"><div>Loading…</div></div>;

  const charity = charityById[pact.charity_id];
  const cad = pact.cadence;
  const prog = pact.progress;
  const status = pact.status;
  const live = LIVE.has(status);
  const review = status === "needs_review";
  const kept = KEPT.has(status);
  const failed = status === "failed";
  const donationDue = status === "donation_pending";
  const donated = DONATED.has(status);
  const declined = DECLINED.has(status);

  const windowOpen =
    !pact.dispute_window_closes_at ||
    new Date(pact.dispute_window_closes_at).getTime() > nowMs;
  const canDispute = failed && windowOpen;

  const cadenceLine = cad
    ? `${cad.days_per_week} days a week · Week ${cad.week_number} of ${cad.weeks}`
    : `${pact.target_count}× · due ${formatDate(pact.deadline_at)}`;

  const statusPill = live
    ? { cls: prog?.behind ? "risk" : "ok", label: prog?.behind ? "At risk" : "On track" }
    : review
    ? { cls: "amber", label: "Under review" }
    : kept
    ? { cls: "ok", label: "Kept" }
    : donationDue || donated
    ? { cls: "risk", label: donated ? "Donated" : "Donation due" }
    : declined
    ? { cls: "muted", label: "Unresolved" }
    : { cls: "risk", label: "Closed" };

  return (
    <div className="pd">
      {/* ── Topbar ── */}
      <div className="pd-top">
        <div className="pd-top-left">
          <button className="pd-icon-btn" onClick={() => navigate("/dashboard")} aria-label="Back">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="17" height="17"><path d="M15 6l-6 6 6 6" /></svg>
          </button>
          <div className="pd-top-glyph"><GoalGlyph title={pact.title} /></div>
          <div>
            <div className="pd-top-title">{pact.title}</div>
            <div className="pd-top-sub m">{cadenceLine}</div>
          </div>
        </div>
        <div className={`pd-pill ${statusPill.cls}`}><span className="dot" />{statusPill.label}</div>
      </div>

      {err && <div className="pd-err">{err}</div>}

      {/* ── ACTIVE ── */}
      {live && (
        <div className="pd-active">
          {/* charcoal hero card */}
          <div className="pd-hero">
            <div className="pd-hero-top">
              <div className="pd-hero-glyph"><GoalGlyph title={pact.title} /></div>
              <div className={`pd-hero-flag ${prog?.behind ? "risk" : "ok"}`}><span className="dot" />{prog?.behind ? "At risk" : "On track"}</div>
            </div>
            <div className="pd-hero-name">{pact.title}</div>
            <div className="pd-hero-sub">{cad ? `${cad.days_per_week} days a week · week ${cad.week_number} of ${cad.weeks}` : pact.goal}</div>
            <div className="pd-hero-week">
              <div className="pd-hero-week-head">
                <span className="m">This week</span>
                <span className="m">{cad ? `${cad.this_week_valid}/${cad.this_week_target}` : `${prog?.valid_count ?? 0}/${prog?.target ?? pact.target_count}`}</span>
              </div>
              <div className="pd-hero-bars">
                {Array.from({ length: cad?.this_week_target ?? pact.target_count }).map((_, i) => (
                  <div key={i} className={`pd-bar${i < (cad?.this_week_valid ?? prog?.valid_count ?? 0) ? " on" : ""}`} />
                ))}
              </div>
            </div>
            <div className="pd-hero-foot">
              <div>
                <div className="pd-hero-k m">On the line</div>
                <div className="pd-hero-stake m">{dollars(pact.stake_amount_cents)}</div>
              </div>
              <div className="ar">
                <div className="pd-hero-k m">Logged</div>
                <div className="pd-hero-streak">{prog?.valid_count ?? 0} days</div>
              </div>
            </div>
            <div className="pd-hero-sig">
              <span className="pd-hero-script">pact</span>
              <span className="pd-hero-no m">No. {pactNo(pact.id)}</span>
            </div>
          </div>

          {/* light right column */}
          <div className="pd-col">
            <div className="pd-col-head">
              {prog?.behind ? "You're behind on this one." : prog && prog.pct >= 80 ? "One session from a clean week." : "Keep the streak alive."}
            </div>
            <div className="pd-col-lede">
              {(prog?.days_left ?? 0) === 0 ? "Deadline's here" : `${prog?.days_left} day${prog?.days_left === 1 ? "" : "s"} left`}.{" "}
              <b>{dollars(pact.stake_amount_cents)} is on the line</b> — log your proof before the deadline and it stays yours.
            </div>
            <button className="pd-submit" onClick={() => setSheetOpen(true)}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="19" height="19"><path d="M4 8h3l1.5-2h7L17 8h3v11H4Z" /><circle cx="12" cy="13" r="3.3" /></svg>
              Submit today's proof
            </button>
            <div className="pd-chips">
              <div className="pd-chip"><span>At stake</span><span className="m risk">{dollars(pact.stake_amount_cents)}</span></div>
              <div className="pd-chip"><span>Goes to</span><span className="b">{charity?.name ?? "your charity"}</span></div>
            </div>
            <button className="pd-cancel" disabled={busy === "cancel"} onClick={() => act("cancel", () => api.cancel(pact.id))}>
              {busy === "cancel" ? "…" : "Cancel pact"}
            </button>
            <button className="pd-coach-strip" onClick={() => setChatOpen(true)}>
              <div className="pd-coach-av">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width="18" height="18"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8Z" /></svg>
              </div>
              <div className="pd-coach-body">
                <span className="m">{pact.agent ?? "Hermes"}</span>
                <div className="pd-coach-last">{coach.length ? coach[coach.length - 1].body : "Your coach is watching this pact. Open the chat anytime."}</div>
              </div>
              <span className="pd-coach-open">Open chat
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" width="15" height="15"><path d="M9 6l6 6-6 6" /></svg>
              </span>
            </button>
          </div>
        </div>
      )}

      {/* ── UNDER REVIEW ── */}
      {review && (
        <div className="pd-center">
          <div className="pd-review-card">
            <div className="pd-review-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="30" height="30"><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></svg>
            </div>
            <div className="pd-review-eyebrow m">Under review</div>
            <div className="pd-review-title">{pact.agent ?? "Hermes"} sent this one to a person.</div>
            <div className="pd-review-body">Your latest proof was close but unclear. A human reviewer is checking it now — we'll update you within 24h. Your streak is <b>paused, not broken</b>.</div>
            <div className="pd-review-steps">
              {["Submitted", "Under review", "Decision"].map((s, i) => (
                <div className="pd-step" key={s}>
                  <span className={`pd-step-dot ${i === 0 ? "done" : i === 1 ? "now" : "todo"}`}>
                    {i === 0 && <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" width="11" height="11"><path d="M5 12.5 10 17l9-11" /></svg>}
                  </span>
                  <span className="pd-step-label">{s}</span>
                </div>
              ))}
            </div>
            <div className="pd-review-actions">
              <button className="pd-btn" onClick={() => navigate("/dashboard")}>Back to home</button>
              <button className="pd-btn ghost" onClick={() => setChatOpen(true)}>Message {pact.agent ?? "Hermes"}</button>
            </div>
          </div>
        </div>
      )}

      {/* ── VERDICT (kept / failed) ── */}
      {(kept || failed) && (
        <div className="pd-center">
          <div className="pd-verdict">
            <div className={`pd-stamp ${kept ? "kept" : "failed"}`}>
              <div className="pd-stamp-ring" />
              <div className="pd-stamp-ring inner" />
              <div className="pd-stamp-mid">
                {kept ? (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" width="38" height="38"><path d="M5 12.5 10 17l9-11" /></svg>
                ) : (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" width="36" height="36"><path d="M6 6l12 12M18 6 6 18" /></svg>
                )}
                <div className="pd-stamp-word m">{kept ? "KEPT" : "FAILED"}</div>
              </div>
            </div>
            <div className={`pd-verdict-eyebrow m ${kept ? "ok" : "risk"}`}>
              {kept ? "Pact kept" : "Pact closed · missed"}
            </div>
            <div className="pd-verdict-title">{kept ? "You kept your word." : "The week got away."}</div>
            <div className="pd-verdict-body">
              {packet?.verdict?.summary ||
                (kept
                  ? `All verified. Your ${dollars(pact.stake_amount_cents)} stays yours — nothing leaves your account.`
                  : `Per your pact, ${dollars(pact.stake_amount_cents)} is due to ${charity?.name ?? "your charity"}.`)}
            </div>
            <div className="pd-verdict-actions">
              {kept ? (
                <>
                  <button className="pd-btn" onClick={() => act("renew", async () => { const f = await api.renew(pact.id); navigate(`/pact/${f.id}`); })}>Start again</button>
                  <button className="pd-btn ghost" onClick={() => navigate("/dashboard")}>Back home</button>
                </>
              ) : (
                <button className="pd-btn" onClick={() => act("settle", () => api.settle(pact.id))}>
                  {busy === "settle" ? "…" : "Resolve donation"}
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" width="16" height="16"><path d="M5 12h13M12 6l6 6-6 6" /></svg>
                </button>
              )}
            </div>
            {canDispute && (
              <div className="pd-dispute">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="18" height="18"><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></svg>
                <div className="pd-dispute-text">
                  <div className="b">Think this is wrong?</div>
                  <div className="s">Add one more proof, or dispute the verdict — one window only.</div>
                </div>
                <button className="pd-btn ghost sm" disabled={busy === "dispute"} onClick={() => act("dispute", () => api.dispute(pact.id))}>Dispute</button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── DONATION DUE ── */}
      {donationDue && (
        <div className="pd-center">
          <div className="pd-donate">
            <div className="pd-donate-head">
              <div className="pd-donate-eyebrow m">Stake due · unresolved</div>
              <div className="pd-donate-amount">
                <span className="m big">{dollars(pact.stake_amount_cents)}</span>
                <span className="to">to {charity?.name ?? "your charity"}</span>
              </div>
              <div className="pd-donate-copy">
                You agreed up front: miss the pact, the stake is donated. Approve the transfer in Link to close it out — or decline and we'll walk you through what that means.
              </div>
            </div>
            <div className="pd-donate-body">
              <div className="pd-method">
                <div className="pd-method-left"><span className="pd-method-mark">L</span><div><div className="b">Link</div><div className="m">•••• 4242</div></div></div>
                <div className="m muted">default method</div>
              </div>
              <div className="pd-donate-actions">
                <button className="pd-btn" onClick={() => setLinkOpen(true)}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="18" height="18"><path d="M5 12.5 10 17l9-11" /></svg>
                  Approve in Link
                </button>
                <button className="pd-btn ghost" onClick={() => setDeclineOpen(true)}>Decline</button>
              </div>
              <div className="pd-donate-note">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><circle cx="12" cy="12" r="9" /><path d="M12 8v.5M12 11v5" /></svg>
                This won't go away until it's resolved. Declining keeps your new pacts paused.
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── DONATED (terminal) ── */}
      {donated && (
        <div className="pd-center">
          <div className="pd-terminal">
            <div className="pd-terminal-icon donated">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="32" height="32"><path d="M12 20s-7-4.3-7-9.2A3.8 3.8 0 0 1 12 8a3.8 3.8 0 0 1 7-1.2c0 4.9-7 13.2-7 13.2Z" /></svg>
            </div>
            <div className="pd-terminal-eyebrow m risk">Donation complete</div>
            <div className="pd-terminal-title">{dollars(pact.stake_amount_cents)} went to {charity?.name ?? "charity"}.</div>
            <div className="pd-terminal-body">Not the outcome you wanted — but the promise still meant something.</div>
            <div className="pd-receipt">
              <div className="pd-receipt-row top"><span className="b">{charity?.name ?? "charity"}</span><span className="m risk">{dollars(pact.stake_amount_cents)}</span></div>
              <div className="pd-receipt-row"><span className="m muted">Receipt</span><span className="m">{(pact.spend_request_id ?? "PCT").slice(-8).toUpperCase()} · via Link •••• 4242</span></div>
            </div>
            <div className="pd-verdict-actions">
              <button className="pd-btn" onClick={() => navigate("/create")}>Start a new pact</button>
              <button className="pd-btn ghost" onClick={() => navigate("/dashboard")}>Back home</button>
            </div>
          </div>
        </div>
      )}

      {/* ── DECLINED / forfeit (terminal) ── */}
      {declined && (
        <div className="pd-center">
          <div className="pd-terminal">
            <div className="pd-terminal-icon declined">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="30" height="30"><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16v.5" /></svg>
            </div>
            <div className="pd-terminal-eyebrow m muted">Donation declined · unresolved</div>
            <div className="pd-terminal-title">This one's still open.</div>
            <div className="pd-terminal-body">You declined the {dollars(pact.stake_amount_cents)} transfer. Per your agreement, <b>new pacts stay paused</b> until this is settled.</div>
            <div className="pd-verdict-actions">
              <button className="pd-btn ghost" onClick={() => navigate("/dashboard")}>Back home</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Overlays ── */}
      {sheetOpen && (
        <SubmitSheet
          pact={pact}
          onClose={() => setSheetOpen(false)}
          onResolved={async () => { await load(); signalChange(); }}
        />
      )}
      {chatOpen && (
        <CoachPane pact={pact} messages={coach} onSend={sendCoach} onClose={() => setChatOpen(false)} />
      )}
      {linkOpen && (
        <LinkModal
          pact={pact}
          charityName={charity?.name ?? "your charity"}
          onClose={() => setLinkOpen(false)}
          onDonated={async () => { setLinkOpen(false); await load(); signalChange(); }}
        />
      )}
      {declineOpen && (
        <DeclineModal
          onClose={() => setDeclineOpen(false)}
          onConfirm={async () => { setDeclineOpen(false); await act("decline", () => api.decline(pact.id)); }}
        />
      )}
    </div>
  );
}

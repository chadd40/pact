import { useCallback, useEffect, useState } from "react";
import { motion } from "motion/react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useClock, useDemo } from "../App";
import { useAppData } from "../data";
import { SubmitSheet } from "./SubmitSheet";
import { CoachPane } from "./CoachPane";
import { LinkModal } from "./LinkModal";
import { DeclineModal } from "./DeclineModal";
import { CardBack, AGENTS } from "../screens/Create";
import { dollars, formatDate } from "../lib";
import type { CoachingMessage, Pact, Packet } from "../types";
// CardBack's editorial `.cb-*` styles live in create.css. It's imported by
// Create.tsx, but PactWorld can render standalone (e.g. tests, deep links) before
// Create is in the bundle — import it here so the card always styles correctly.
import "../screens/create.css";

const LIVE = new Set(["active", "evaluating"]);
const KEPT = new Set(["succeeded", "canceled_release"]);
const DONATED = new Set(["donated", "donation_failed"]);
const DECLINED = new Set(["donation_declined", "canceled_forfeit"]);

// Default coach avatar when the pact's agent has none (or no agent set).
const HERMES_AVATAR = "/agents/Hermes.svg";

export interface PactWorldProps {
  pactId: string;
  mode: "standalone" | "overlay";
  /** Overlay mode: invoked by the backdrop / close button. */
  onClose?: () => void;
  /**
   * Test seam (used ONLY by PactWorld.test.tsx): seed the rendered pact directly
   * so the component tree renders without the live api.getPact/getCoach/packet
   * chain. Not used in the app.
   */
  initialPact?: Pact;
}

export function PactWorld({ pactId, mode, onClose, initialPact }: PactWorldProps) {
  const { bump, signalChange } = useDemo();
  const nowMs = useClock();
  const { charityById } = useAppData();
  const navigate = useNavigate();

  const [pact, setPact] = useState<Pact | null>(initialPact ?? null);
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
  // the live dispute-window countdown in render only. When `initialPact` is
  // supplied (tests), skip the network load entirely.
  useEffect(() => { if (!initialPact) load(); }, [load, bump, initialPact]);

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

  const goBack = () => {
    if (mode === "overlay") onClose?.();
    else navigate("/dashboard");
  };

  if (err && !pact) {
    return (
      <div className="pd-missing">
        <div>{err}</div>
        <button className="pd-btn" onClick={goBack}>Back to home</button>
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

  // ── Live pact → editorial CardBack props ──────────────────────────────────
  // Every section is "done": the pact is sealed, so all values are present and
  // locked. days/weeks prefer the derived cadence, falling back to the pact's
  // own fields. The agent resolves through the AGENTS catalog (default Hermes).
  const days = cad?.days_per_week ?? pact.days_per_week ?? 0;
  const weeks = cad?.weeks ?? pact.weeks ?? 0;
  const weeksWord = weeks === 1 ? "week" : "weeks";
  const cbAgent = AGENTS.find((a) => a.key === pact.agent) ?? AGENTS[0];
  const cbCharity = charityById[pact.charity_id] ?? null;
  const sealedDate = formatDate(pact.started_at ?? pact.created_at).toUpperCase();

  // Coach strip avatar/name (active/evaluating). Fall back to Hermes when the
  // pact's agent has no avatar in the catalog.
  const coachAvatar = cbAgent.avatar ?? HERMES_AVATAR;
  const coachName = pact.agent ?? "Hermes";

  // ── The status-keyed right panel ──────────────────────────────────────────
  const panelForStatus = () => {
    // ACTIVE / EVALUATING — submit panel
    if (live) {
      return (
        <div className="pd-col">
          <div className="pd-col-head">
            {prog?.behind ? "You're behind on this one." : prog && prog.pct >= 80 ? "One session from a clean week." : "Keep the streak alive."}
          </div>
          <div className="pd-col-lede">
            {(prog?.days_left ?? 0) === 0 ? "Deadline's here" : `${prog?.days_left} day${prog?.days_left === 1 ? "" : "s"} left`}.{" "}
            <b>{dollars(pact.stake_amount_cents)} is on the line</b> — log your proof before the deadline and it stays yours.
          </div>
          {/* This-week pill — moved here from the (now editorial) left card. */}
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
          <button className="pd-submit" onClick={() => setSheetOpen(true)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="19" height="19"><path d="M4 8h3l1.5-2h7L17 8h3v11H4Z" /><circle cx="12" cy="13" r="3.3" /></svg>
            Submit today's proof
          </button>
          <button className="pd-cancel" disabled={busy === "cancel"} onClick={() => act("cancel", () => api.cancel(pact.id))}>
            {busy === "cancel" ? "…" : "Cancel pact"}
          </button>
          <button className="pd-coach-strip" onClick={() => setChatOpen(true)}>
            <div className="pd-coach-av">
              <img src={coachAvatar} alt="" />
            </div>
            <div className="pd-coach-body">
              <span className="pd-coach-name m"><em>{coachName}</em></span>
              <div className="pd-coach-last">{coach.length ? coach[coach.length - 1].body : "Your coach is watching this pact. Open the chat anytime."}</div>
            </div>
            <span className="pd-coach-open">Open chat
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" width="15" height="15"><path d="M9 6l6 6-6 6" /></svg>
            </span>
          </button>
        </div>
      );
    }

    // UNDER REVIEW
    if (review) {
      return (
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
            <button className="pd-btn" onClick={goBack}>Back to home</button>
            <button className="pd-btn ghost" onClick={() => setChatOpen(true)}>Message {pact.agent ?? "Hermes"}</button>
          </div>
        </div>
      );
    }

    // VERDICT — kept / failed
    if (kept || failed) {
      return (
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
                <button className="pd-btn ghost" onClick={goBack}>Back home</button>
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
      );
    }

    // DONATION DUE
    if (donationDue) {
      return (
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
      );
    }

    // DONATED — receipt terminal
    if (donated) {
      return (
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
            <button className="pd-btn ghost" onClick={goBack}>Back home</button>
          </div>
        </div>
      );
    }

    // DECLINED / forfeit — terminal
    if (declined) {
      return (
        <div className="pd-terminal">
          <div className="pd-terminal-icon declined">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="30" height="30"><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16v.5" /></svg>
          </div>
          <div className="pd-terminal-eyebrow m muted">Donation declined · unresolved</div>
          <div className="pd-terminal-title">This one's still open.</div>
          <div className="pd-terminal-body">You declined the {dollars(pact.stake_amount_cents)} transfer. Per your agreement, <b>new pacts stay paused</b> until this is settled.</div>
          <div className="pd-verdict-actions">
            <button className="pd-btn ghost" onClick={goBack}>Back home</button>
          </div>
        </div>
      );
    }

    return null;
  };

  return (
    <div className={`world world--${mode}`}>
      {mode === "overlay" && <div className="world-backdrop" onClick={() => onClose?.()} />}

      <div className="world-stage">
        {/* Top chrome: standalone gets a back button; overlay gets a close X. */}
        {mode === "standalone" ? (
          <button className="world-back" onClick={goBack} aria-label="Back to home">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="17" height="17"><path d="M15 6l-6 6 6 6" /></svg>
            Back
          </button>
        ) : (
          <button className="world-close" onClick={() => onClose?.()} aria-label="Close">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" width="17" height="17"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        )}

        {err && <div className="pd-err">{err}</div>}

        <div className="world-grid">
          {/* LEFT — the editorial card back, fed with the live pact (shared
              layoutId with the Home carousel card so Task 8 can flip it). */}
          <motion.div className="world-card" layoutId={`pact-card-${pactId}`}>
            <CardBack
              goalName={pact.title}
              days={days}
              weeks={weeks}
              weeksWord={weeksWord}
              stake={pact.stake_amount_cents / 100}
              charity={cbCharity}
              agent={cbAgent}
              owner={pact.owner}
              sealedDate={sealedDate}
              titleReady
              freqReady
              stakeReady
              charityReady
              agentReady
              signed
              zoneState={() => "done"}
            />
          </motion.div>

          {/* RIGHT — status-keyed panel. */}
          <div className="world-panel">{panelForStatus()}</div>
        </div>
      </div>

      {/* ── Overlays / modals ── */}
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

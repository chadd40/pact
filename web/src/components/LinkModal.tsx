import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { dollars } from "../lib";
import type { Pact } from "../types";

type Phase = "confirm" | "awaiting" | "done";

// Two-phase Link donation: Confirm → "approve in your Link app, we're watching" →
// monitor (poll) → captured → Donated. In demo/test mode the approval is auto-
// simulated after a beat (and the "I approved" button forces it immediately); real
// money movement stays behind the backend payment-provider gate.
export function LinkModal({
  pact,
  charityName,
  onClose,
  onDonated,
}: {
  pact: Pact;
  charityName: string;
  onClose: () => void;
  onDonated: () => Promise<void> | void;
}) {
  const [phase, setPhase] = useState<Phase>("confirm");
  const [err, setErr] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);
  const autoRef = useRef<number | null>(null);

  const stopTimers = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    if (autoRef.current) { clearTimeout(autoRef.current); autoRef.current = null; }
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && phase === "confirm") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, phase]);

  useEffect(() => () => stopTimers(), [stopTimers]);

  const finish = useCallback(async () => {
    stopTimers();
    setPhase("done");
    // brief success beat, then let the detail re-render to the Donated terminal
    setTimeout(() => { onDonated(); }, 900);
  }, [onDonated, stopTimers]);

  const startMonitoring = useCallback(() => {
    // poll the donation state (the "we're watching for it")
    pollRef.current = window.setInterval(async () => {
      const s = await api.donationStatus(pact.id).catch(() => null);
      if (s?.state === "donated") finish();
    }, 1500);
    // auto-simulate the Link approval arriving after a short beat (demo)
    autoRef.current = window.setTimeout(() => { approveNow(); }, 2600);
  }, [pact.id, finish]);

  const confirm = async () => {
    setErr(null);
    try {
      await api.donationInitiate(pact.id);
      setPhase("awaiting");
      startMonitoring();
    } catch {
      setErr("Couldn't open the Link request. Try again.");
    }
  };

  const approveNow = async () => {
    const s = await api.donationApprove(pact.id).catch(() => null);
    if (s?.state === "donated") finish();
  };

  return (
    <div className="ov center" role="dialog" aria-modal="true">
      <div className="ov-backdrop" onClick={() => phase === "confirm" && onClose()} />
      <div className="lm">
        {phase === "confirm" && (
          <>
            <div className="lm-head">
              <div className="lm-brand"><span className="lm-mark">L</span>Pay with Link</div>
              <span className="m lm-secure">secured</span>
            </div>
            <div className="lm-body">
              <div className="m lm-to">Donating to {charityName}</div>
              <div className="m lm-amount">{dollars(pact.stake_amount_cents)}</div>
              <div className="lm-method"><span className="lm-card" /><span className="m">•••• 4242</span>
                <svg viewBox="0 0 24 24" fill="none" stroke="var(--pc-kept)" strokeWidth="2.2" width="16" height="16"><path d="M5 12.5 10 17l9-11" /></svg>
              </div>
              <button className="ov-btn" onClick={confirm}>Confirm {dollars(pact.stake_amount_cents)} donation</button>
              <button className="lm-cancel" onClick={onClose}>Cancel</button>
              {err && <div className="ov-err">{err}</div>}
            </div>
          </>
        )}

        {phase === "awaiting" && (
          <div className="lm-await">
            <div className="lm-spinner" />
            <div className="lm-await-h">Approve in your Link app</div>
            <div className="lm-await-p">We sent the request to Link. Open the Link app and approve the {dollars(pact.stake_amount_cents)} transfer — <b>we're watching for it</b> and will finish the moment you do.</div>
            <button className="ov-btn" onClick={approveNow}>I approved it in Link</button>
            <div className="m lm-await-poll"><span className="dot" />Waiting for approval…</div>
          </div>
        )}

        {phase === "done" && (
          <div className="lm-await">
            <div className="lm-tick"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" width="34" height="34"><path d="M5 12.5 10 17l9-11" /></svg></div>
            <div className="lm-await-h">Donation sent</div>
            <div className="lm-await-p">{dollars(pact.stake_amount_cents)} is on its way to {charityName}.</div>
          </div>
        )}
      </div>
    </div>
  );
}

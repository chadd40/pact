import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { dollars } from "../lib";
import { useFocusTrap } from "./useFocusTrap";
import type { DonationStateName, Pact } from "../types";

type Phase = "confirm" | "awaiting" | "done" | "error";

// Two-phase Link donation: Confirm → "approve in your Link app, we're watching" →
// monitor (poll) → captured → Donated. In demo/test mode the approval is auto-
// simulated after a beat (and the "I approved" button forces it immediately); real
// money movement stays behind the backend payment-provider gate. A provider error
// surfaces as a terminal "error" phase rather than spinning forever.
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
  const modalRef = useRef<HTMLDivElement>(null);

  // ESC/focus-trap: closeable everywhere except the brief terminal "done" beat.
  useFocusTrap(modalRef, onClose, { closeOnEsc: phase !== "done" });

  const stopTimers = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    if (autoRef.current) { clearTimeout(autoRef.current); autoRef.current = null; }
  }, []);
  useEffect(() => () => stopTimers(), [stopTimers]);

  const finish = useCallback(() => {
    stopTimers();
    setPhase("done");
    // brief success beat, then let the detail re-render to the Donated terminal
    setTimeout(() => { onDonated(); }, 900);
  }, [onDonated, stopTimers]);

  const fail = useCallback((msg: string) => {
    stopTimers();
    setErr(msg);
    setPhase("error");
  }, [stopTimers]);

  // Map a donation state to a terminal transition. Returns true if it was terminal.
  const apply = useCallback((state: DonationStateName | undefined): boolean => {
    if (state === "donated") { finish(); return true; }
    if (state === "error") { fail("Link couldn't complete the transfer — no money moved."); return true; }
    if (state === "declined") { stopTimers(); onClose(); return true; }
    return false;
  }, [finish, fail, stopTimers, onClose]);

  const approveNow = useCallback(async () => {
    try {
      const s = await api.donationApprove(pact.id);
      apply(s.state);
    } catch {
      fail("Couldn't confirm the approval. Try again.");
    }
  }, [pact.id, apply, fail]);

  const startMonitoring = useCallback(() => {
    // Poll the donation state (the "we're watching for it").
    pollRef.current = window.setInterval(async () => {
      const s = await api.donationStatus(pact.id).catch(() => null);
      if (s) apply(s.state);
    }, 1500);
    // Auto-simulate the Link approval arriving after a short beat (demo); the
    // "I approved" button does the same immediately. Real Link: the agent calls
    // approve when it detects the in-app approval.
    autoRef.current = window.setTimeout(() => { approveNow(); }, 2600);
  }, [pact.id, apply, approveNow]);

  const confirm = useCallback(async () => {
    setErr(null);
    try {
      const s = await api.donationInitiate(pact.id);
      if (apply(s.state)) return; // already terminal (donated/error)
      setPhase("awaiting");
      startMonitoring();
    } catch {
      fail("Couldn't open the Link request. Try again.");
    }
  }, [pact.id, apply, startMonitoring, fail]);

  const retry = useCallback(() => { setErr(null); setPhase("confirm"); }, []);

  const announce =
    phase === "awaiting" ? "Waiting for approval in your Link app"
    : phase === "done" ? "Donation sent"
    : phase === "error" ? (err ?? "Something went wrong")
    : "";

  return (
    <div className="ov center" role="dialog" aria-modal="true" aria-label="Pay with Link">
      <div className="ov-backdrop" onClick={() => phase === "confirm" && onClose()} />
      <div className="lm" ref={modalRef} tabIndex={-1}>
        <div className="sr-only" role="status" aria-live="polite">{announce}</div>

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

        {phase === "error" && (
          <div className="lm-await">
            <div className="lm-err-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" width="30" height="30"><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16v.5" /></svg></div>
            <div className="lm-await-h">Couldn't complete in Link</div>
            <div className="lm-await-p">{err ?? "No money moved. You can try again, or close and resolve this later."}</div>
            <button className="ov-btn" onClick={retry}>Try again</button>
            <button className="lm-cancel" onClick={onClose}>Close</button>
          </div>
        )}
      </div>
    </div>
  );
}

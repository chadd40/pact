import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { dollars } from "../lib";
import type { Pact } from "../types";

type Phase = "waiting" | "approved";

// Create-time stake approval. When a short pact is sealed it pre-authorizes the
// stake in Link and parks at awaiting_stake; this overlay is the human-in-the-loop
// beat where the owner approves the spend tied to THIS pact. It polls
// /stake/confirm (idempotent — awaiting_stake until the human approves, active once
// the card is provisioned) and only advances once the pact is active AND a minimum
// spin beat has elapsed, so the "waiting for Link approval → approved" transition
// reads clearly. In live mode the wait is the real Link approval; in dry-run/demo
// the confirm returns active immediately and the beat carries the animation.
const MIN_SPIN_MS = 10_000;
const POLL_MS = 2_000;
const DONE_BEAT_MS = 1_000;

export function StakeApprovalModal({
  pact,
  onApproved,
}: {
  pact: Pact;
  onApproved: (pact: Pact) => void;
}) {
  const [phase, setPhase] = useState<Phase>("waiting");
  const onApprovedRef = useRef(onApproved);
  useEffect(() => {
    onApprovedRef.current = onApproved;
  });

  useEffect(() => {
    let cancelled = false;
    const startedAt = Date.now();
    let pollTimer: number | undefined;
    let doneTimer: number | undefined;
    let beatTimer: number | undefined;

    const finish = (approved: Pact) => {
      const remaining = Math.max(0, MIN_SPIN_MS - (Date.now() - startedAt));
      doneTimer = window.setTimeout(() => {
        if (cancelled) return;
        setPhase("approved");
        beatTimer = window.setTimeout(() => {
          if (!cancelled) onApprovedRef.current(approved);
        }, DONE_BEAT_MS);
      }, remaining);
    };

    const poll = async () => {
      if (cancelled) return;
      try {
        const p = await api.stakeConfirm(pact.id);
        if (cancelled) return;
        if (p.status === "active") {
          finish(p);
          return;
        }
      } catch {
        /* transient — keep waiting for the approval */
      }
      pollTimer = window.setTimeout(poll, POLL_MS);
    };
    poll();

    return () => {
      cancelled = true;
      clearTimeout(pollTimer);
      clearTimeout(doneTimer);
      clearTimeout(beatTimer);
    };
  }, [pact.id]);

  const announce =
    phase === "approved"
      ? "Link approval received"
      : "Waiting for approval in your Link app";

  return (
    <div className="ov center" role="dialog" aria-modal="true" aria-label="Approve the stake in Link">
      <div className="ov-backdrop" />
      <div className="lm" tabIndex={-1}>
        <div className="sr-only" role="status" aria-live="polite">{announce}</div>

        {phase === "waiting" && (
          <div className="lm-await">
            <div className="lm-spinner" />
            <div className="lm-await-h">Waiting for Link approval</div>
            <div className="lm-await-p">
              You staked {dollars(pact.stake_amount_cents)} on this pact. Approve the
              hold in your Link app so the stake is armed — <b>we're watching for it</b>
              {" "}and will seal the pact the moment you do.
            </div>
          </div>
        )}

        {phase === "approved" && (
          <div className="lm-await">
            <div className="lm-tick">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" width="34" height="34"><path d="M5 12.5 10 17l9-11" /></svg>
            </div>
            <div className="lm-await-h">Approved</div>
            <div className="lm-await-p">
              {dollars(pact.stake_amount_cents)} is armed in Link. It only moves to
              charity if you miss the pact.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

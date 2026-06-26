import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, DEMO_OWNER } from "../api";
import { useDemo } from "../App";
import { WaxSeal } from "../components/WaxSeal";
import { dollars } from "../lib";
import type { Pact, Packet, Proof } from "../types";

export function VerdictScreen() {
  const { pactId } = useParams();
  const navigate = useNavigate();
  const { nowMs, signalChange } = useDemo();
  const [pact, setPact] = useState<Pact | null>(null);
  const [packet, setPacket] = useState<Packet | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [renewing, setRenewing] = useState(false);

  // dispute flow
  const [disputeOpen, setDisputeOpen] = useState(false);
  const [disputePhase, setDisputePhase] = useState<"proof" | "submitting" | "added">("proof");
  const [disputeToken, setDisputeToken] = useState("");
  const [disputeBusy, setDisputeBusy] = useState(false);
  const [disputeNote, setDisputeNote] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = async () => {
    // If the pact is due but not yet settled, settle it so a verdict exists. A pact
    // sitting in `needs_review` is intentionally NOT auto-settled — no money has moved
    // and we render its own suspended state below.
    const p = await api.getPact(pactId!);
    setPact(p);
    const terminal = [
      "succeeded",
      "failed",
      "donated",
      "donation_failed",
      "donation_declined",
      "canceled_forfeit",
    ];
    if (p.status !== "needs_review" && !terminal.includes(p.status)) {
      await api.settle(pactId!).catch(() => {});
    }
    const pk = await api.packet(pactId!).catch(() => null);
    setPacket(pk);
    return p;
  };

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        await refresh();
      } catch (e) {
        if (alive) setError(e instanceof ApiError ? e.detail : "No verdict available yet.");
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pactId]);

  if (error) {
    return (
      <div className="page">
        <Link to="/" className="backlink">
          ← The ledger
        </Link>
        <div className="empty">
          <p className="serif-italic" style={{ fontSize: 20 }}>
            {error}
          </p>
          <p className="muted">
            This pact may still be in force. Advance the demo clock past its deadline to
            settle it.
          </p>
        </div>
      </div>
    );
  }

  // ── needs_review: a distinct "under review" state. No money has moved. ──
  if (pact && pact.status === "needs_review") {
    return (
      <div className="page">
        <Link to="/" className="backlink">
          ← The ledger
        </Link>
        <div className="verdict-stage">
          <div className="reveal-up" style={{ textAlign: "center" }}>
            <span className="mono-label" style={{ letterSpacing: "0.3em" }}>
              § UNDER REVIEW · {pact.title} §
            </span>
          </div>
          <div className="review-card reveal-up" style={{ "--d": "0.2s" } as React.CSSProperties}>
            <span className="chip chip-review">Under review</span>
            <h2 style={{ fontSize: 26, margin: "16px 0 8px" }}>No money has moved.</h2>
            <p className="muted" style={{ maxWidth: 480 }}>
              One or more proofs couldn't be judged automatically and are being reviewed.
              Your stake is untouched until the review resolves — it may still clear to a
              keep. Check back after the next sweep.
            </p>
          </div>
        </div>
        {packet && <EvidenceLedger packet={packet} />}
      </div>
    );
  }

  if (!packet || !pact) {
    return (
      <div className="page">
        <div className="center-note">
          <span className="spin" /> Sealing the verdict…
        </div>
      </div>
    );
  }

  const v = packet.verdict;
  const kept = v.status === "succeeded";
  const stakeDollars = dollars(packet.pact.stake_amount_cents);
  const centerLine = kept ? "$0 MOVED" : `${stakeDollars} → CHARITY`;

  // The single dispute window: a FAILED pact whose window is still open (or not yet
  // stamped closed). One extra proof can overturn it to succeeded; otherwise it's final.
  const windowOpen =
    !pact.dispute_window_closes_at ||
    new Date(pact.dispute_window_closes_at).getTime() > nowMs;
  const canDispute = v.status === "failed" && windowOpen;

  // ── dispute: add one proof, then call /dispute to re-judge the window. ──
  const getDisputeToken = async () => {
    setDisputeBusy(true);
    try {
      const { token } = await api.proofToken(pact.id);
      setDisputeToken(token);
    } finally {
      setDisputeBusy(false);
    }
  };

  const addDisputeProof = async (proofFn: () => Promise<Proof>) => {
    setDisputeBusy(true);
    setDisputeNote(null);
    try {
      await proofFn();
      setDisputePhase("added");
    } catch (e) {
      setDisputeNote(e instanceof ApiError ? e.detail : "That proof was rejected.");
    } finally {
      setDisputeBusy(false);
    }
  };

  const submitDispute = async () => {
    setDisputePhase("submitting");
    setDisputeBusy(true);
    try {
      const verdict = await api.dispute(pact.id);
      signalChange();
      setDisputeNote(
        verdict.status === "succeeded"
          ? "Overturned — your extra proof cleared the bar. Stake released, $0 moved."
          : "Reviewed and upheld — still short of the target. This verdict is final."
      );
      await refresh();
      setDisputeOpen(false);
      setDisputePhase("proof");
      setDisputeToken("");
    } catch (e) {
      setDisputeNote(e instanceof ApiError ? e.detail : "Dispute could not be submitted.");
      setDisputePhase("added");
    } finally {
      setDisputeBusy(false);
    }
  };

  const renew = async () => {
    setRenewing(true);
    try {
      const fresh = await api.renew(pactId!);
      await api.setOwner(fresh.id, DEMO_OWNER).catch(() => {});
      signalChange();
      navigate(`/confirm/${fresh.id}`);
    } catch (e) {
      alert(e instanceof ApiError ? e.detail : "Could not renew.");
      setRenewing(false);
    }
  };

  return (
    <div className="page">
      <Link to="/" className="backlink">
        ← The ledger
      </Link>

      {/* Stage: the stamp pressed over the evidence */}
      <div className="verdict-stage">
        <div className="reveal-up" style={{ textAlign: "center" }}>
          <span className="mono-label" style={{ letterSpacing: "0.3em" }}>
            § VERDICT · {packet.pact.title} §
          </span>
        </div>

        <div style={{ marginTop: 18 }}>
          <WaxSeal kept={kept} centerLine={centerLine} />
        </div>

        <div className="verdict-summary">
          <div className="reveal-up" style={{ "--d": "0.7s" } as React.CSSProperties}>
            <div
              className="banner-line"
              style={{ color: kept ? "var(--kept-green)" : "var(--stake-red)" }}
            >
              {kept ? "You kept your word." : "The stake moved."}
            </div>
            <p className="muted">{v.summary}</p>
            <p className="serif-italic muted" style={{ marginTop: 10 }}>
              {packet.honesty_note}
            </p>
          </div>
        </div>
      </div>

      {/* Receipt */}
      <div className="reveal-up" style={{ "--d": "0.85s" } as React.CSSProperties}>
        <div className="receipt">
          <div>
            <div className="mono-label" style={{ marginBottom: 6 }}>
              {kept ? "Settlement" : "Donation receipt"}
            </div>
            {kept ? (
              <div className="receipt-ref">
                $0 moved — stake released. Proof {v.valid_proof_count}/{v.target_count}.
              </div>
            ) : (
              <div className="receipt-ref">
                {stakeDollars} → {packet.pact.charity_id.replace(/_/g, " ")}
                {v.payment_ref ? ` · ref ${v.payment_ref}` : ""}
              </div>
            )}
          </div>
          <span
            className="chip"
            style={{ color: kept ? "var(--kept-green)" : "var(--stake-red)" }}
          >
            {v.payment_action.replace(/_/g, " ") || (kept ? "released" : "—")}
          </span>
        </div>
      </div>

      {/* Dispute affordance — a single honest window on a fresh fail. */}
      {canDispute && (
        <div className="reveal-up" style={{ marginTop: 26, "--d": "0.9s" } as React.CSSProperties}>
          <div className="dispute-card">
            <div className="dispute-head">
              <strong style={{ fontFamily: "var(--font-display)", fontSize: 19 }}>
                Believe this is wrong?
              </strong>
              <span className="mono-label">One dispute window</span>
            </div>
            <p className="muted" style={{ fontSize: 14.5, margin: "8px 0 14px" }}>
              Submit one more proof to dispute this verdict. If it clears the target, the
              verdict is overturned to <em>kept</em> and your stake is released. If it
              doesn't, the failure stands — this is your single window.
            </p>

            {!disputeOpen ? (
              <button className="btn btn-sm" onClick={() => setDisputeOpen(true)}>
                ⚖ Dispute this verdict
              </button>
            ) : (
              <div className="dispute-flow">
                {disputePhase === "proof" && !disputeToken && (
                  <button className="btn btn-sm" onClick={getDisputeToken} disabled={disputeBusy}>
                    {disputeBusy ? <span className="spin" /> : null} Get proof token
                  </button>
                )}

                {disputePhase === "proof" && disputeToken && (
                  <>
                    <p className="muted" style={{ fontSize: 14, marginBottom: 4 }}>
                      Write <strong>{disputeToken}</strong> in-frame, then add your proof:
                    </p>
                    <div className="nonce">{disputeToken}</div>
                    <input
                      ref={fileRef}
                      type="file"
                      accept="image/*"
                      className="proof-file"
                      disabled={disputeBusy}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f)
                          addDisputeProof(() =>
                            api.uploadProofImage(pact.id, disputeToken, f, true)
                          );
                      }}
                    />
                    <div style={{ display: "flex", gap: 10, marginTop: 12, flexWrap: "wrap" }}>
                      <button
                        className="btn btn-sm"
                        onClick={() => fileRef.current?.click()}
                        disabled={disputeBusy}
                      >
                        {disputeBusy ? <span className="spin" /> : "▣"} Add photo proof
                      </button>
                      <button
                        className="btn btn-sm btn-ghost"
                        onClick={() =>
                          addDisputeProof(() =>
                            api.submitProof(pact.id, {
                              modality: "text",
                              token: disputeToken,
                              content_ok: true,
                            })
                          )
                        }
                        disabled={disputeBusy}
                      >
                        Add log instead
                      </button>
                    </div>
                  </>
                )}

                {disputePhase === "added" && (
                  <>
                    <p className="muted" style={{ fontSize: 14, marginBottom: 12 }}>
                      Proof added. Submit the dispute to have the auditor re-judge the window.
                    </p>
                    <button
                      className="btn btn-sm btn-seal"
                      onClick={submitDispute}
                      disabled={disputeBusy}
                    >
                      {disputeBusy ? <span className="spin" /> : "⚖"} Submit dispute
                    </button>
                  </>
                )}

                {disputePhase === "submitting" && (
                  <div className="center-note" style={{ padding: "16px 0" }}>
                    <span className="spin" /> Re-judging the window…
                  </div>
                )}

                {disputeNote && <div className="dispute-note">{disputeNote}</div>}
              </div>
            )}
          </div>
        </div>
      )}

      <EvidenceLedger packet={packet} />

      {/* Coaching log */}
      {packet.coaching_log.length > 0 && (
        <div
          className="reveal-up"
          style={{ marginTop: 40, "--d": "1.05s" } as React.CSSProperties}
        >
          <div className="eyebrow" style={{ marginBottom: 14 }}>
            <span className="mono-label">Coaching log</span>
            <span className="rule" />
          </div>
          <div className="coach-body" style={{ padding: 0, gap: 10 }}>
            {packet.coaching_log.map((m) => (
              <div
                key={m.id}
                className={`msg ${m.direction === "inbound" ? "user-msg" : "coach-msg"}`}
              >
                {m.direction !== "inbound" && (
                  <div className="msg-trigger">{m.trigger || "coach"}</div>
                )}
                {m.body}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Renew */}
      <div
        className="reveal-up"
        style={
          {
            marginTop: 44,
            display: "flex",
            gap: 14,
            justifyContent: "center",
            "--d": "1.15s",
          } as React.CSSProperties
        }
      >
        <button className="btn" onClick={renew} disabled={renewing}>
          {renewing ? <span className="spin" /> : "↻"} Renew this pact
        </button>
        <Link to="/" className="btn btn-ghost">
          Back to the ledger
        </Link>
      </div>
    </div>
  );
}

function EvidenceLedger({ packet }: { packet: Packet }) {
  const v = packet.verdict;
  return (
    <div className="reveal-up" style={{ marginTop: 40, "--d": "0.95s" } as React.CSSProperties}>
      <div className="eyebrow" style={{ marginBottom: 14 }}>
        <span className="mono-label">Evidence ledger</span>
        <span className="rule" />
        <span className="mono-label">
          {v.valid_proof_count}/{v.target_count} valid
        </span>
      </div>
      <div className="ledger">
        {packet.proofs.length === 0 && (
          <div className="muted" style={{ padding: "16px 0" }}>
            No proofs were filed against this pact.
          </div>
        )}
        {packet.proofs.map((p) => (
          <div className="ledger-row" key={p.id}>
            <span className="ledger-date">{p.date || "—"}</span>
            <span className={`ledger-status ${p.status}`}>{p.status}</span>
            <span className="ledger-reason">{p.judge_reason}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, DEMO_OWNER } from "../api";
import { useDemo } from "../App";
import { WaxSeal } from "../components/WaxSeal";
import { dollars } from "../lib";
import type { Packet } from "../types";

export function VerdictScreen() {
  const { pactId } = useParams();
  const navigate = useNavigate();
  const { signalChange } = useDemo();
  const [packet, setPacket] = useState<Packet | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [renewing, setRenewing] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        // If the pact is due but not yet settled, settle it so a verdict exists.
        const pact = await api.getPact(pactId!);
        const terminal = [
          "succeeded",
          "failed",
          "donated",
          "donation_failed",
          "donation_declined",
          "canceled_forfeit",
        ];
        if (!terminal.includes(pact.status)) {
          await api.settle(pactId!).catch(() => {});
        }
        const pk = await api.packet(pactId!);
        if (alive) setPacket(pk);
      } catch (e) {
        if (alive) setError(e instanceof ApiError ? e.detail : "No verdict available yet.");
      }
    })();
    return () => {
      alive = false;
    };
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
          <p className="muted">This pact may still be in force. Advance the demo clock past
          its deadline to settle it.</p>
        </div>
      </div>
    );
  }

  if (!packet) {
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

  const renew = async () => {
    setRenewing(true);
    try {
      const fresh = await api.renew(pactId!);
      await api.setOwner(fresh.id, DEMO_OWNER).catch(() => {});
      signalChange();
      // Renew returns a fresh draft → send the user back through Confirm.
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
            <div className="banner-line" style={{ color: kept ? "var(--kept-green)" : "var(--stake-red)" }}>
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

      {/* Evidence ledger */}
      <div
        className="reveal-up"
        style={{ marginTop: 40, "--d": "0.95s" } as React.CSSProperties}
      >
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

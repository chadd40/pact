import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, DEMO_OWNER } from "../api";
import { useDemo } from "../App";
import { Reveal } from "../components/Reveal";
import { countdown, dollars, isTerminal, pace } from "../lib";
import type { CoachingMessage, Pact, Proof } from "../types";

// Photo flow: idle → token issued (write nonce, pick photo) → result (judge verdict).
// "log" is the secondary text modality (existing JSON /proofs), kept for parity.
type ProofMode = "photo" | "log";
type ProofPhase = "idle" | "token" | "result";

export function Active() {
  const { pactId } = useParams();
  const navigate = useNavigate();
  const { nowMs, bump, signalChange } = useDemo();

  const [pact, setPact] = useState<Pact | null>(null);
  const [proofs, setProofs] = useState<Proof[]>([]);
  const [coach, setCoach] = useState<CoachingMessage[]>([]);
  const [nudges, setNudges] = useState<CoachingMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);

  // proof flow
  const [mode, setMode] = useState<ProofMode>("photo");
  const [phase, setPhase] = useState<ProofPhase>("idle");
  const [token, setToken] = useState("");
  const [lastProof, setLastProof] = useState<Proof | null>(null);
  const [proofBusy, setProofBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [showCancel, setShowCancel] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const coachBodyRef = useRef<HTMLDivElement>(null);

  // Server-truth: the pact, its real proofs, the coach thread, and any pending nudges.
  const load = async () => {
    const [p, ps, msgs, ob] = await Promise.all([
      api.getPact(pactId!),
      api.getProofs(pactId!).catch(() => [] as Proof[]),
      api.getCoach(pactId!).catch(() => [] as CoachingMessage[]),
      api.outbox(DEMO_OWNER).catch(() => [] as CoachingMessage[]),
    ]);
    setPact(p);
    setProofs(ps);
    setCoach(msgs);
    // Only surface nudges that belong to THIS pact and haven't been delivered.
    setNudges(ob.filter((m) => m.pact_id === p.id && !m.delivered_at));
    // If the pact has already settled (e.g. advance-day passed deadline), route to verdict.
    if (isTerminal(p.status)) navigate(`/verdict/${p.id}`, { replace: true });
  };

  useEffect(() => {
    let alive = true;
    (async () => {
      if (alive) await load();
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pactId, bump]);

  useEffect(() => {
    coachBodyRef.current?.scrollTo({ top: 1e6, behavior: "smooth" });
  }, [coach.length]);

  if (!pact) {
    return (
      <div className="page">
        <div className="center-note">
          <span className="spin" /> Opening the pact…
        </div>
      </div>
    );
  }

  // Distinct-day passed proofs — straight from server-truth, no session accumulation.
  const validCount = new Set(
    proofs.filter((p) => p.status === "passed").map((p) => p.day_bucket)
  ).size;
  const cd = countdown(pact.deadline_at, nowMs);

  // ── proof flow ──
  const getToken = async () => {
    setProofBusy(true);
    try {
      const { token } = await api.proofToken(pact.id);
      setToken(token);
      setPhase("token");
    } finally {
      setProofBusy(false);
    }
  };

  const onResult = (proof: Proof) => {
    setLastProof(proof);
    setPhase("result");
  };

  const onError = (e: unknown) => {
    setLastProof({
      id: "err",
      pact_id: pact.id,
      modality: mode === "photo" ? "photo" : "text",
      received_at: "",
      day_bucket: "",
      token_issued: token,
      token_ok: false,
      phash: null,
      dup_of: null,
      artifact_path: null,
      status: "failed",
      judge_reason: e instanceof ApiError ? e.detail : "Submission rejected.",
      judge_checklist: {},
    });
    setPhase("result");
  };

  // Real photo proof: EXIF-stripped, stored, pHashed and judged server-side.
  const uploadPhoto = async (file: File) => {
    setProofBusy(true);
    try {
      const proof = await api.uploadProofImage(pact.id, token, file, true);
      onResult(proof);
      await load();
    } catch (e) {
      onError(e);
    } finally {
      setProofBusy(false);
    }
  };

  // Secondary text modality (the existing JSON /proofs route).
  const submitLog = async (contentOk: boolean) => {
    setProofBusy(true);
    try {
      const proof = await api.submitProof(pact.id, {
        modality: "text",
        token,
        content_ok: contentOk,
      });
      onResult(proof);
      await load();
    } catch (e) {
      onError(e);
    } finally {
      setProofBusy(false);
    }
  };

  const resetProof = () => {
    setPhase("idle");
    setToken("");
    setLastProof(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  const sendCoach = async () => {
    if (!draft.trim()) return;
    setSending(true);
    const text = draft.trim();
    setDraft("");
    try {
      const { inbound, outbound } = await api.postCoach(pact.id, text);
      setCoach((c) => [...c, inbound, outbound]);
    } finally {
      setSending(false);
    }
  };

  // Demo "check in": run a scheduler sweep so a proactive nudge lands, then show it.
  const checkIn = async () => {
    setActionBusy("tick");
    try {
      await api.tick();
      await load();
    } catch (e) {
      alert(e instanceof ApiError ? e.detail : "Check-in unavailable.");
    } finally {
      setActionBusy(null);
    }
  };

  const dismissNudge = async (id: string) => {
    setNudges((ns) => ns.filter((n) => n.id !== id));
    await api.markDelivered(id).catch(() => {});
  };

  const useFreeze = async () => {
    setActionBusy("freeze");
    try {
      await api.freeze(pact.id);
      await load();
      signalChange();
    } catch (e) {
      alert(e instanceof ApiError ? e.detail : "Freeze unavailable.");
    } finally {
      setActionBusy(null);
    }
  };

  // Cancel: in the cooling-off window the stake is RELEASED (canceled_release);
  // after it, canceling FORFEITS the stake to charity (donation → donated).
  const cancelPact = async () => {
    setActionBusy("cancel");
    try {
      const result = await api.cancel(pact.id);
      signalChange();
      const released = result.status === "canceled_release";
      alert(
        released
          ? "Canceled within the cooling-off window — your stake was released. $0 moved."
          : "Pact canceled after the cooling-off window — the stake was forfeited to your charity."
      );
      navigate(isTerminal(result.status) ? `/verdict/${result.id}` : "/");
    } catch (e) {
      alert(e instanceof ApiError ? e.detail : "Cancel unavailable.");
      setActionBusy(null);
    }
  };

  const freezesLeft = pact.freezes_allowed - pact.freezes_used;

  return (
    <div className="page">
      <Link to="/" className="backlink">
        ← The ledger
      </Link>

      <Reveal>
        <Reveal.Item>
          <div className="eyebrow" style={{ marginBottom: 14 }}>
            <span className="mono-label">Active pact · in force</span>
            <span className="rule" />
            <span className="chip chip-active">Active</span>
          </div>
        </Reveal.Item>

        <Reveal.Item>
          <h1 style={{ fontSize: "clamp(28px,4vw,40px)", marginBottom: 6 }}>{pact.title}</h1>
          <p className="serif-italic muted" style={{ marginBottom: 4 }}>
            {pact.goal}
          </p>
        </Reveal.Item>
      </Reveal>

      <div className="active-grid" style={{ marginTop: 28 }}>
        {/* LEFT — countdown, pace, proof flow */}
        <Reveal>
          <Reveal.Item>
            <div className="mono-label" style={{ marginBottom: 8 }}>
              {cd.past ? "Deadline passed — awaiting settle" : "Time remaining"}
            </div>
            <div className="countdown">
              <Unit n={cd.days} l="days" />
              <span className="cd-sep">:</span>
              <Unit n={cd.hours} l="hrs" />
              <span className="cd-sep">:</span>
              <Unit n={cd.minutes} l="min" />
              <span className="cd-sep">:</span>
              <Unit n={cd.seconds} l="sec" />
            </div>

            <div className="pace-line">{pace(pact, validCount, nowMs)}</div>

            <div className="proofdots">
              {Array.from({ length: pact.target_count }).map((_, i) => (
                <div key={i} className={`proofdot ${i < validCount ? "filled" : ""}`}>
                  {i < validCount ? "✓" : i + 1}
                </div>
              ))}
            </div>
          </Reveal.Item>

          {/* proof submission */}
          <Reveal.Item>
            <div className="proof-panel">
              <div className="proof-modes">
                <button
                  className={`proof-tab ${mode === "photo" ? "active" : ""}`}
                  onClick={() => {
                    setMode("photo");
                    resetProof();
                  }}
                >
                  Photo proof
                </button>
                <button
                  className={`proof-tab ${mode === "log" ? "active" : ""}`}
                  onClick={() => {
                    setMode("log");
                    resetProof();
                  }}
                >
                  Log instead
                </button>
              </div>

              {phase === "idle" && (
                <>
                  <p className="muted" style={{ fontSize: 14, margin: "10px 0 12px" }}>
                    {mode === "photo"
                      ? "Get a one-time token, write it on paper or your phone, then take a photo with it in-frame. The auditor judges it server-side."
                      : "Get a one-time token, then log a written note as your evidence."}
                  </p>
                  <button className="btn btn-sm" onClick={getToken} disabled={proofBusy}>
                    {proofBusy ? <span className="spin" /> : null} Get proof token
                  </button>
                </>
              )}

              {phase === "token" && (
                <>
                  <p className="muted" style={{ fontSize: 14, margin: "10px 0 4px" }}>
                    {mode === "photo" ? (
                      <>
                        Write <strong>{token}</strong> on paper or your phone and include it
                        in the photo so the auditor can verify it's live:
                      </>
                    ) : (
                      <>Write this nonce in your note so the auditor can verify it's live:</>
                    )}
                  </p>
                  <div className="nonce">{token}</div>

                  {mode === "photo" ? (
                    <>
                      <input
                        ref={fileRef}
                        type="file"
                        accept="image/*"
                        className="proof-file"
                        disabled={proofBusy}
                        onChange={(e) => {
                          const f = e.target.files?.[0];
                          if (f) uploadPhoto(f);
                        }}
                      />
                      <button
                        className="btn btn-sm"
                        style={{ marginTop: 12 }}
                        onClick={() => fileRef.current?.click()}
                        disabled={proofBusy}
                      >
                        {proofBusy ? <span className="spin" /> : "▣"} Take / choose photo
                      </button>
                      <p className="mono-label" style={{ marginTop: 8 }}>
                        EXIF stripped · stored · pHashed · judged
                      </p>
                    </>
                  ) : (
                    <div style={{ display: "flex", gap: 10 }}>
                      <button
                        className="btn btn-sm"
                        onClick={() => submitLog(true)}
                        disabled={proofBusy}
                      >
                        {proofBusy ? <span className="spin" /> : null} Submit log
                      </button>
                      <button
                        className="btn btn-sm btn-ghost"
                        onClick={() => submitLog(false)}
                        disabled={proofBusy}
                        title="Simulate evidence that doesn't satisfy the rubric"
                      >
                        Submit weak log
                      </button>
                    </div>
                  )}
                </>
              )}

              {phase === "result" && lastProof && (
                <>
                  <ProofVerdict proof={lastProof} />
                  <button
                    className="btn btn-sm btn-ghost"
                    style={{ marginTop: 12 }}
                    onClick={resetProof}
                  >
                    Submit another
                  </button>
                </>
              )}
            </div>
          </Reveal.Item>

          {/* real proof log (server-truth) */}
          <Reveal.Item>
            <div className="proof-log">
              <div className="mono-label" style={{ marginBottom: 6 }}>
                Filed proofs · {proofs.length}
              </div>
              {proofs.length === 0 ? (
                <p className="muted" style={{ fontSize: 13.5 }}>
                  No proofs filed yet. Your first one starts the ledger.
                </p>
              ) : (
                <div className="ledger">
                  {proofs.map((p) => (
                    <div className="ledger-row compact" key={p.id}>
                      <span className="ledger-date">{p.day_bucket || "—"}</span>
                      <span className={`ledger-status ${p.status}`}>{p.status}</span>
                      <span className="ledger-reason">{p.judge_reason}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Reveal.Item>

          <Reveal.Item>
            <div className="active-actions">
              <button
                className="btn btn-ghost btn-sm"
                onClick={useFreeze}
                disabled={!!actionBusy || freezesLeft <= 0}
                title={freezesLeft <= 0 ? "No freezes left" : "Extend the deadline once"}
              >
                {actionBusy === "freeze" ? <span className="spin" /> : "❄"} Use a freeze (
                {freezesLeft})
              </button>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => setShowCancel((s) => !s)}
                disabled={!!actionBusy}
              >
                ✕ Cancel pact
              </button>
              <span className="mono-label" style={{ alignSelf: "center" }}>
                Stake {dollars(pact.stake_amount_cents)}
              </span>
            </div>
            {showCancel && (
              <div className="cancel-panel">
                <p style={{ fontSize: 14, marginBottom: 12 }}>
                  Cancel now (within the cooling-off window) and your stake is released —
                  $0 moves. After that, canceling forfeits the stake to your charity.
                </p>
                <div style={{ display: "flex", gap: 10 }}>
                  <button
                    className="btn btn-sm btn-seal"
                    onClick={cancelPact}
                    disabled={actionBusy === "cancel"}
                  >
                    {actionBusy === "cancel" ? <span className="spin" /> : null} Confirm cancel
                  </button>
                  <button
                    className="btn btn-sm btn-ghost"
                    onClick={() => setShowCancel(false)}
                    disabled={actionBusy === "cancel"}
                  >
                    Keep the pact
                  </button>
                </div>
              </div>
            )}
          </Reveal.Item>
        </Reveal>

        {/* RIGHT — coach thread (the ally) + proactive nudges */}
        <Reveal>
          <Reveal.Item>
            <div className="coach">
              <div className="coach-head">
                <span className="brand-mark" style={{ color: "var(--sealed-gold)" }}>
                  §
                </span>
                <strong style={{ fontFamily: "var(--font-display)", fontSize: 17 }}>
                  Your coach
                </strong>
                <button
                  className="checkin-btn"
                  onClick={checkIn}
                  disabled={!!actionBusy}
                  title="Run a scheduler sweep so the coach checks in"
                >
                  {actionBusy === "tick" ? <span className="spin" /> : "↻"} Check in
                </button>
              </div>

              {nudges.length > 0 && (
                <div className="nudge-strip">
                  {nudges.map((n) => (
                    <div className="nudge" key={n.id}>
                      <div className="msg-trigger">proactive nudge · {n.trigger || "coach"}</div>
                      <div>{n.body}</div>
                      <button className="nudge-dismiss" onClick={() => dismissNudge(n.id)}>
                        Mark read
                      </button>
                    </div>
                  ))}
                </div>
              )}

              <div className="coach-body" ref={coachBodyRef}>
                {coach.length === 0 && (
                  <div className="msg coach-msg">
                    <div className="msg-trigger">opening</div>
                    You signed it — I'm in your corner. {pact.target_count} reps across distinct
                    days. Send me a note any time and I'll help you stay on pace.
                  </div>
                )}
                {coach.map((m) => (
                  <div
                    key={m.id}
                    className={`msg reveal-up ${m.direction === "inbound" ? "user-msg" : "coach-msg"}`}
                  >
                    {m.direction !== "inbound" && (
                      <div className="msg-trigger">{m.trigger || "coach"}</div>
                    )}
                    {m.body}
                  </div>
                ))}
              </div>
              <div className="coach-compose">
                <input
                  type="text"
                  placeholder="Tell your coach how it's going…"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && sendCoach()}
                />
                <button className="btn btn-sm" onClick={sendCoach} disabled={sending || !draft.trim()}>
                  {sending ? <span className="spin" /> : "Send"}
                </button>
              </div>
            </div>
          </Reveal.Item>
        </Reveal>
      </div>
    </div>
  );
}

function Unit({ n, l }: { n: number; l: string }) {
  return (
    <div className="cd-unit">
      <div className="cd-num">{String(n).padStart(2, "0")}</div>
      <div className="cd-lbl">{l}</div>
    </div>
  );
}

function ProofVerdict({ proof }: { proof: Proof }) {
  const mark =
    proof.status === "passed" ? "✓ PASSED" : proof.status === "failed" ? "✕ FAILED" : "? REVIEW";
  return (
    <div className={`proof-verdict reveal-up ${proof.status}`}>
      <span className="pv-mark">{mark}</span>
      <div>
        <div>{proof.judge_reason}</div>
        {proof.token_issued && (
          <div className="mono-label" style={{ marginTop: 6 }}>
            token {proof.token_issued} · {proof.token_ok ? "verified" : "not verified"}
          </div>
        )}
      </div>
    </div>
  );
}

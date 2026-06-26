import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { useDemo } from "../App";
import { Reveal } from "../components/Reveal";
import { countdown, dollars, isTerminal, pace } from "../lib";
import type { CoachingMessage, Pact, Proof } from "../types";

type ProofPhase = "idle" | "token" | "result";

export function Active() {
  const { pactId } = useParams();
  const navigate = useNavigate();
  const { nowMs, bump, signalChange } = useDemo();

  const [pact, setPact] = useState<Pact | null>(null);
  const [proofs, setProofs] = useState<Proof[]>([]);
  const [coach, setCoach] = useState<CoachingMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);

  // proof flow
  const [phase, setPhase] = useState<ProofPhase>("idle");
  const [token, setToken] = useState("");
  const [lastProof, setLastProof] = useState<Proof | null>(null);
  const [proofBusy, setProofBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const coachBodyRef = useRef<HTMLDivElement>(null);

  // The backend exposes no GET for in-flight proofs (they're only queryable via the
  // packet once a verdict exists), so we accumulate proofs submitted this session
  // locally. `seedCount` carries any pre-existing distinct-day proofs the demo seeded.
  const [seedCount, setSeedCount] = useState(0);

  const load = async () => {
    const [p, msgs] = await Promise.all([
      api.getPact(pactId!),
      api.getCoach(pactId!).catch(() => []),
    ]);
    setPact(p);
    setCoach(msgs);
    // The seeded LIVE pact ships with 2 passed proofs on distinct days (demo.py).
    if (p.id === "pact-live") setSeedCount(2);
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

  // Distinct-day passed proofs: seeded baseline + those submitted this session.
  const sessionDays = new Set(
    proofs.filter((p) => p.status === "passed").map((p) => p.day_bucket)
  ).size;
  const validCount = seedCount + sessionDays;
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

  const submitProof = async (contentOk: boolean) => {
    setProofBusy(true);
    try {
      const proof = await api.submitProof(pact.id, {
        modality: "text",
        token,
        content_ok: contentOk,
      });
      setLastProof(proof);
      setProofs((ps) => [...ps, proof]);
      setPhase("result");
      await load();
    } catch (e) {
      setLastProof({
        id: "err",
        pact_id: pact.id,
        modality: "text",
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
    } finally {
      setProofBusy(false);
    }
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
              <div className="mono-label" style={{ marginBottom: 4 }}>
                Submit proof · {pact.rubric.modality}
              </div>
              {phase === "idle" && (
                <>
                  <p className="muted" style={{ fontSize: 14, marginBottom: 12 }}>
                    Get a one-time token, write it in-frame, then submit your evidence.
                  </p>
                  <button className="btn btn-sm" onClick={getToken} disabled={proofBusy}>
                    {proofBusy ? <span className="spin" /> : null} Get proof token
                  </button>
                </>
              )}

              {phase === "token" && (
                <>
                  <p className="muted" style={{ fontSize: 14, marginBottom: 4 }}>
                    Write this nonce in-frame so the auditor can verify it's live:
                  </p>
                  <div className="nonce">{token}</div>
                  <div style={{ display: "flex", gap: 10 }}>
                    <button
                      className="btn btn-sm"
                      onClick={() => submitProof(true)}
                      disabled={proofBusy}
                    >
                      {proofBusy ? <span className="spin" /> : null} Submit valid proof
                    </button>
                    <button
                      className="btn btn-sm btn-ghost"
                      onClick={() => submitProof(false)}
                      disabled={proofBusy}
                      title="Simulate evidence that doesn't satisfy the rubric"
                    >
                      Submit weak proof
                    </button>
                  </div>
                </>
              )}

              {phase === "result" && lastProof && (
                <>
                  <ProofVerdict proof={lastProof} />
                  <button
                    className="btn btn-sm btn-ghost"
                    style={{ marginTop: 12 }}
                    onClick={() => {
                      setPhase("idle");
                      setToken("");
                      setLastProof(null);
                    }}
                  >
                    Submit another
                  </button>
                </>
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
              <span className="mono-label" style={{ alignSelf: "center" }}>
                Stake {dollars(pact.stake_amount_cents)} · advance the demo clock from the
                console to reach the deadline
              </span>
            </div>
          </Reveal.Item>
        </Reveal>

        {/* RIGHT — coach thread (the ally) */}
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
                <span className="mono-label" style={{ marginLeft: "auto" }}>
                  Ally
                </span>
              </div>
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

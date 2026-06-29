import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useClock, useDemo } from "../App";
import { useAppData } from "../data";
import { CoachPane } from "./CoachPane";
import { LinkModal } from "./LinkModal";
import { DeclineModal } from "./DeclineModal";
import { CardBack, CustomCardFront, AGENTS } from "../screens/Create";
import { GoalGlyph } from "./GoalGlyph";
import { cardArtFor } from "../lib/cardArt";
import { asset } from "../lib/asset";
import { dollars, formatDate, formatDateTime } from "../lib";
import type { CoachingMessage, Pact, Packet, ProofStatus } from "../types";
// CardBack's editorial `.cb-*` styles live in create.css. It's imported by
// Create.tsx, but PactWorld can render standalone (e.g. tests, deep links) before
// Create is in the bundle — import it here so the card always styles correctly.
import "../screens/create.css";

const LIVE = new Set(["active", "evaluating"]);
const KEPT = new Set(["succeeded", "canceled_release"]);
const DONATED = new Set(["donated"]);
const DECLINED = new Set(["donation_declined", "canceled_forfeit"]);

// Default coach avatar when the pact's agent has none (or no agent set).
const HERMES_AVATAR = asset("/agents/Hermes.svg");
const PAPER_TURN = "transform .74s cubic-bezier(.18,.78,.22,1)";

export interface PactWorldProps {
  pactId: string;
  /**
   * Test seam (used ONLY by PactWorld.test.tsx): seed the rendered pact directly
   * so the component tree renders without the live api.getPact/getCoach/packet
   * chain. Not used in the app.
   */
  initialPact?: Pact;
}

interface FlipRect { x: number; y: number; width: number; height: number; }
type ProofFlow = "idle" | "choice" | "fresh" | "choosing" | "analyzing" | ProofStatus | "error";

export function PactWorld({ pactId, initialPact }: PactWorldProps) {
  const { bump, signalChange } = useDemo();
  const nowMs = useClock();
  const { charityById } = useAppData();
  const navigate = useNavigate();
  const location = useLocation();

  const [pact, setPact] = useState<Pact | null>(initialPact ?? null);
  const [coach, setCoach] = useState<CoachingMessage[]>([]);
  const [packet, setPacket] = useState<Packet | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [receiptRef, setReceiptRef] = useState("");
  const [receiptErr, setReceiptErr] = useState<string | null>(null);

  const [proofFlow, setProofFlow] = useState<ProofFlow>("idle");
  const [proofToken, setProofToken] = useState<string | null>(null);
  const [proofErr, setProofErr] = useState<string | null>(null);
  const [proofCount, setProofCount] = useState(0);
  const proofCountRef = useRef(0);
  const proofRecoverRef = useRef<ProofFlow>("choice");
  const proofPickerFallbackRef = useRef<number | null>(null);
  const proofInputRef = useRef<HTMLInputElement>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [linkOpen, setLinkOpen] = useState(false);
  const [declineOpen, setDeclineOpen] = useState(false);

  // ── Create-style flip-open entry (Task 8) ──────────────────────────────────
  // Home.openPact navigates here with `state.flipFrom` = the clicked carousel
  // card's on-screen rect. We run a true two-faced create-style flip (no Framer
  // layout), separating POSITION from ROTATION:
  //   · the OUTER wrapper (.world-card, wrapRef) takes the position FLIP —
  //     translate/scale from the clicked card's rect back to identity.
  //   · the FLIP container (.world-flip, flipRef, preserve-3d) takes the rotateY —
  //     starts at 0° (showing the FRONT art, matching the clicked card) and plays
  //     to 180° (revealing the editorial back), which is also its rest state.
  // Two backface-hidden faces mean a face is always visible during the flip — the
  // single-face version was invisible for its first half (it faced away).
  // Capture `flipFrom` ONCE — meaningful only on the first render. (Demo bump /
  // refetch must not re-arm the flip; we latch it in a ref.)
  const flipFromRef = useRef<FlipRect | null>(
    (location.state as { flipFrom?: FlipRect } | null)?.flipFrom ?? null
  );
  const wrapRef = useRef<HTMLDivElement>(null);   // position FLIP target
  const flipRef = useRef<HTMLDivElement>(null);   // rotation target
  const [entering, setEntering] = useState(false);
  const ranFlip = useRef(false);

  // The card only mounts once `pact` has loaded (before that we render a "Loading…"
  // placeholder). So the FLIP can't run on the very first paint when the pact is
  // fetched async — gate on the card being present and re-run (via the `pact` dep)
  // once it mounts. The `ranFlip` latch keeps it to a single run.
  useLayoutEffect(() => {
    if (ranFlip.current) return;          // once per PactWorld instance
    const flipFrom = flipFromRef.current;
    if (!flipFrom) { ranFlip.current = true; return; }  // direct/keyboard → no flip
    const wrap = wrapRef.current;
    const flip = flipRef.current;
    if (!wrap || !flip) return;           // card not mounted yet (pact still loading)
    ranFlip.current = true;
    // Respect reduced-motion. `matchMedia` may be absent in test/jsdom — guard it.
    const reduce =
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return;                   // CSS rest class shows the editorial back

    setEntering(true);                    // drop the rest class; show the front at 0°

    // LAST — the card's natural centered box. FIRST — the carousel card's rect.
    const last = wrap.getBoundingClientRect();
    if (last.width === 0 || last.height === 0) {
      // No real layout (e.g. jsdom): flag the entry + a marker inline transform so
      // the treatment is observable, but skip the (meaningless) numeric math.
      wrap.style.transform = "translate(0px, 0px)";
      return;
    }
    const dx = flipFrom.x - last.x;
    const dy = flipFrom.y - last.y;
    const sx = flipFrom.width / last.width;
    const sy = flipFrom.height / last.height;

    // INVERT — wrapper jumps to the clicked card's position/scale; flip container
    // sits at 0° (front showing), both with no transition.
    wrap.style.transition = "none";
    wrap.style.transformOrigin = "top left";
    wrap.style.transform = `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})`;
    flip.style.transition = "none";
    flip.style.transform = "rotateY(0deg)";

    let raf2 = 0;
    const onEnd = (e: TransitionEvent) => {
      if (e.propertyName !== "transform" || e.target !== wrap) return;
      // Clear the wrapper's inline position (so resize isn't broken). Leave the
      // flip container at its rest 180° — handled by the CSS `--rest` class once
      // `entering` flips false; clearing the inline transform lets that take over.
      wrap.style.transition = "";
      wrap.style.transform = "";
      wrap.style.transformOrigin = "";
      flip.style.transition = "";
      flip.style.transform = "";
      wrap.removeEventListener("transitionend", onEnd);
      setEntering(false);
    };

    // PLAY — next frame, release the wrapper to identity and rotate the flip
    // container to 180° (revealing the editorial back). A double rAF guarantees the
    // inverted frame is committed before the transition starts.
    const raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => {
        wrap.style.transition = PAPER_TURN;
        wrap.style.transform = "none";
        flip.style.transition = PAPER_TURN;
        flip.style.transform = "rotateY(180deg)";
        wrap.addEventListener("transitionend", onEnd);
      });
    });

    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
      wrap.removeEventListener("transitionend", onEnd);
    };
    // The card mounts only after `pact` loads, so re-run when it appears.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pact]);

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

  useEffect(() => {
    if (!pact?.id) return;
    let alive = true;
    api.getProofs(pact.id)
      .then((proofs) => {
        if (!alive) return;
        proofCountRef.current = proofs.length;
        setProofCount(proofs.length);
      })
      .catch(() => {
        if (!alive) return;
        proofCountRef.current = 0;
        setProofCount(0);
      });
    return () => { alive = false; };
  }, [pact?.id, bump]);

  useEffect(() => () => {
    if (proofPickerFallbackRef.current != null) {
      window.clearTimeout(proofPickerFallbackRef.current);
    }
  }, []);

  const sendCoach = async (text: string, attachments: File[] = []) => {
    if (!pact) return;
    await api.postCoach(pact.id, text, attachments).catch(() => {});
    setCoach(await api.getCoach(pact.id).catch(() => coach));
  };

  const act = async (kind: string, fn: () => Promise<unknown>) => {
    setBusy(kind); setErr(null);
    try { await fn(); await load(); signalChange(); }
    catch { setErr("That didn't go through. Try again."); }
    finally { setBusy(null); }
  };

  const ensureProofToken = async (): Promise<string> => {
    if (!pact) throw new Error("Missing pact.");
    if (proofToken) return proofToken;
    const next = await api.proofToken(pact.id);
    setProofToken(next.token);
    return next.token;
  };

  const openProofChoices = () => {
    setProofErr(null);
    if (proofCountRef.current > 0 || proofCount > 0) {
      pickProofFile("idle");
      return;
    }
    setProofFlow((flow) => (flow === "choice" ? "idle" : "choice"));
  };

  const chooseFreshProof = async () => {
    setProofErr(null);
    setProofFlow("fresh");
    try {
      await ensureProofToken();
    } catch {
      setProofErr("Couldn't create a fresh proof code. Try again.");
      setProofFlow("error");
    }
  };

  const pickProofFile = (recoverTo: ProofFlow = proofCountRef.current > 0 ? "idle" : "choice") => {
    setProofErr(null);
    proofRecoverRef.current = recoverTo;
    setProofFlow("choosing");
    proofInputRef.current?.click();
    if (proofPickerFallbackRef.current != null) {
      window.clearTimeout(proofPickerFallbackRef.current);
    }
    proofPickerFallbackRef.current = window.setTimeout(() => {
      proofPickerFallbackRef.current = null;
      setProofFlow((flow) => (flow === "choosing" ? proofRecoverRef.current : flow));
    }, 1200);
  };

  const onProofFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (proofPickerFallbackRef.current != null) {
      window.clearTimeout(proofPickerFallbackRef.current);
      proofPickerFallbackRef.current = null;
    }
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || !pact) {
      setProofFlow((flow) => (flow === "choosing" ? proofRecoverRef.current : flow));
      return;
    }
    setProofErr(null);
    setProofFlow("analyzing");
    try {
      const token = await ensureProofToken();
      const proof = await api.uploadProofImage(pact.id, token, file);
      setProofFlow(proof.status);
      proofCountRef.current = Math.max(proofCountRef.current + 1, 1);
      setProofCount(proofCountRef.current);
      await load();
      signalChange();
    } catch {
      setProofErr("Couldn't submit that proof. Try another file.");
      setProofFlow("error");
    }
  };

  const proofButtonLabel = () => {
    if (proofFlow === "choosing") return "Opening file picker...";
    if (proofFlow === "analyzing") return "Analyzing proof...";
    if (proofFlow === "passed") return "Proof verified";
    if (proofFlow === "ambiguous") return "Needs review";
    if (proofFlow === "failed") return "Proof failed";
    if (proofFlow === "error") return "Try proof again";
    return "Submit today's proof";
  };

  const submitReceipt = async () => {
    if (!pact) return;
    const raw = receiptRef.trim();
    if (!raw) { setReceiptErr("Enter the receipt number or URL."); return; }
    const isUrl = /^https?:\/\//i.test(raw);
    setBusy("receipt"); setReceiptErr(null);
    try {
      await api.recordDonationReceipt(pact.id, {
        receipt_source: "manual",
        receipt_ref: isUrl ? null : raw,
        receipt_url: isUrl ? raw : null,
        confirmation_notes: "Entered by the owner in Pact.",
      });
      setReceiptRef("");
      await load();
      signalChange();
    } catch {
      setReceiptErr("Couldn't save that receipt. Try again.");
    } finally {
      setBusy(null);
    }
  };

  const goBack = () => {
    navigate("/dashboard");
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
  const donationFailed = status === "donation_failed";
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
  // Card FRONT art — the SAME art the Home carousel shows for this pact, so the
  // flip-open front matches the card the user clicked (Task 8 two-faced flip).
  const cbArt = cardArtFor(pact);

  // Coach strip avatar/name (active/evaluating). Fall back to Hermes when the
  // pact's agent has no avatar in the catalog.
  const coachAvatar = cbAgent.avatar ?? HERMES_AVATAR;
  const coachName = pact.agent ?? "Hermes";
  const proofStepIndex =
    proofFlow === "choice"
      ? 0
      : proofFlow === "fresh" || proofFlow === "choosing"
      ? 1
      : 2;
  const proofSteps = ["Choose mode", "Prepare proof", "Agent verdict"];

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
          <input ref={proofInputRef} type="file" accept="image/*" hidden onChange={onProofFile} />
          <button
            className={`pd-submit proof-${proofFlow}${proofFlow === "choosing" || proofFlow === "analyzing" ? " is-busy" : ""}`}
            onClick={openProofChoices}
            disabled={proofFlow === "choosing" || proofFlow === "analyzing"}
          >
            {proofFlow === "choosing" || proofFlow === "analyzing" ? (
              <span className="pd-spinner" aria-hidden="true" />
            ) : proofFlow === "passed" ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" width="18" height="18"><path d="M5 12.5 10 17l9-11" /></svg>
            ) : proofFlow === "failed" ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" width="18" height="18"><path d="M6 6l12 12M18 6 6 18" /></svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="19" height="19"><path d="M4 8h3l1.5-2h7L17 8h3v11H4Z" /><circle cx="12" cy="13" r="3.3" /></svg>
            )}
            {proofButtonLabel()}
          </button>
          {proofFlow !== "idle" && (
            <div className={`pd-proof-panel proof-${proofFlow}`} data-proof-flow={proofFlow}>
              <div className="pd-proof-rail" aria-hidden="true">
                {proofSteps.map((step, index) => (
                  <span
                    key={step}
                    className={`pd-proof-step${index === proofStepIndex ? " is-active" : ""}${index < proofStepIndex ? " is-done" : ""}`}
                  >
                    {step}
                  </span>
                ))}
              </div>
              {proofErr && <div className="pd-proof-error">{proofErr}</div>}
              {proofFlow === "choice" && (
                <>
                  <div className="pd-proof-title">Is this happening now?</div>
                  <div className="pd-proof-copy">Use a fresh code for live check-ins, or upload existing evidence without writing anything into the photo.</div>
                  <div className="pd-proof-actions">
                    <button type="button" aria-label="Yes, use a fresh code" onClick={chooseFreshProof}>
                      <span>Yes, use a fresh code</span>
                      <small>Best for live check-ins</small>
                    </button>
                    <button type="button" aria-label="No, upload evidence" onClick={() => pickProofFile("choice")}>
                      <span>No, upload evidence</span>
                      <small>No code written on the image</small>
                    </button>
                  </div>
                </>
              )}
              {proofFlow === "fresh" && (
                <>
                  <div className="pd-proof-title">Fresh proof code</div>
                  <div className="pd-proof-copy">Put this code somewhere visible in the photo, then upload it here.</div>
                  <code className="pd-proof-code m">{proofToken?.toUpperCase() ?? "PACT-..."}</code>
                  <button className="pd-proof-upload" type="button" onClick={() => pickProofFile("fresh")}>
                    Upload coded photo
                  </button>
                </>
              )}
              {proofFlow === "choosing" && (
                <>
                  <div className="pd-proof-title">Choose your proof file</div>
                  <div className="pd-proof-copy">Pick a photo or screenshot. The submit button will keep spinning once analysis starts.</div>
                </>
              )}
              {proofFlow === "analyzing" && (
                <>
                  <div className="pd-proof-title">Hermes is checking the proof</div>
                  <div className="pd-proof-copy">Your agent is verifying the image against the pact. The button will flash with the result.</div>
                </>
              )}
              {proofFlow === "passed" && (
                <>
                  <div className="pd-proof-title">Proof verified</div>
                  <div className="pd-proof-copy">Logged. Your agent accepted this proof.</div>
                </>
              )}
              {proofFlow === "ambiguous" && (
                <>
                  <div className="pd-proof-title">Needs review</div>
                  <div className="pd-proof-copy">This one is close enough for review. Your streak is paused, not broken.</div>
                </>
              )}
              {proofFlow === "failed" && (
                <>
                  <div className="pd-proof-title">Proof failed</div>
                  <div className="pd-proof-copy">The proof did not pass. You can try again with clearer evidence.</div>
                </>
              )}
              {proofFlow === "error" && (
                <>
                  <div className="pd-proof-title">Couldn't submit that proof</div>
                  <div className="pd-proof-copy">Try a clearer file or start with a fresh code.</div>
                  <button className="pd-proof-upload" type="button" onClick={() => setProofFlow("choice")}>
                    Choose another proof
                  </button>
                </>
              )}
            </div>
          )}
          <div className="pd-bottom-stack">
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
            <button className="pd-cancel" disabled={busy === "cancel"} onClick={() => act("cancel", () => api.cancel(pact.id))}>
              {busy === "cancel" ? "…" : "Cancel pact"}
            </button>
          </div>
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

    // DONATION FAILED — approval denied/expired/provider error terminal
    if (donationFailed) {
      return (
        <div className="pd-terminal">
          <div className="pd-terminal-icon declined">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="30" height="30"><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16v.5" /></svg>
          </div>
          <div className="pd-terminal-eyebrow m muted">Donation not completed</div>
          <div className="pd-terminal-title">No transfer was confirmed.</div>
          <div className="pd-terminal-body">The miss is recorded, but Link did not produce an approved donation. Review the payment attempt before starting another pact.</div>
          <div className="pd-verdict-actions">
            <button className="pd-btn ghost" onClick={goBack}>Back home</button>
          </div>
        </div>
      );
    }

    // DONATED — approval terminal, receipt-aware
    if (donated) {
      const receiptStatus = packet?.verdict.receipt_status ?? "unconfirmed";
      const receiptConfirmed = receiptStatus === "manual_receipt" || receiptStatus === "provider_confirmed";
      const receiptLabel =
        receiptStatus === "provider_confirmed" ? "Provider confirmed"
        : receiptStatus === "manual_receipt" ? "Manual receipt"
        : "Receipt unconfirmed";
      const receiptEvidence =
        packet?.verdict.receipt_ref ||
        packet?.verdict.receipt_url ||
        packet?.verdict.receipt_artifact_path ||
        null;
      return (
        <div className="pd-terminal">
          <div className="pd-terminal-icon donated">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="32" height="32"><path d="M12 20s-7-4.3-7-9.2A3.8 3.8 0 0 1 12 8a3.8 3.8 0 0 1 7-1.2c0 4.9-7 13.2-7 13.2Z" /></svg>
          </div>
          <div className="pd-terminal-eyebrow m risk">
            {receiptConfirmed ? "Donation confirmed" : "Donation approved"}
          </div>
          <div className="pd-terminal-title">
            {receiptConfirmed
              ? `${dollars(pact.stake_amount_cents)} is confirmed for ${charity?.name ?? "charity"}.`
              : `${dollars(pact.stake_amount_cents)} was approved for ${charity?.name ?? "charity"}.`}
          </div>
          <div className="pd-terminal-body">
            {receiptConfirmed
              ? "Receipt evidence is attached to the final packet."
              : "Link approval is recorded. Add the charity receipt when you have it so the packet can say the payout landed."}
          </div>
          <div className="pd-receipt">
            <div className="pd-receipt-row top"><span className="b">{charity?.name ?? "charity"}</span><span className="m risk">{dollars(pact.stake_amount_cents)}</span></div>
            <div className="pd-receipt-row"><span className="m muted">Link approval</span><span className="m">{(pact.spend_request_id ?? "PCT").slice(-8).toUpperCase()}</span></div>
            <div className="pd-receipt-row"><span className="m muted">Receipt</span><span className={`m ${receiptConfirmed ? "ok" : "pending"}`}>{receiptEvidence ?? receiptLabel}</span></div>
            {packet?.verdict.confirmed_at && (
              <div className="pd-receipt-row"><span className="m muted">Confirmed</span><span className="m">{formatDateTime(packet.verdict.confirmed_at)}</span></div>
            )}
          </div>
          {!receiptConfirmed && (
            <form
              className="pd-receipt-form"
              onSubmit={(e) => { e.preventDefault(); void submitReceipt(); }}
            >
              <label className="sr-only" htmlFor={`receipt-${pact.id}`}>Charity receipt number or URL</label>
              <input
                id={`receipt-${pact.id}`}
                className="pd-receipt-input"
                value={receiptRef}
                onChange={(e) => setReceiptRef(e.target.value)}
                placeholder="Receipt number or URL"
              />
              <button className="pd-btn sm" disabled={busy === "receipt"} type="submit">
                {busy === "receipt" ? "Saving…" : "Record receipt"}
              </button>
              {receiptErr && <div className="pd-receipt-err">{receiptErr}</div>}
            </form>
          )}
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
    <div className={`world world--standalone${entering ? " world--entering" : ""}`}>
      <div className="world-stage">
        {/* Top chrome: standalone back button to the dashboard. */}
        <button className="world-back" onClick={goBack} aria-label="Back to home">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="17" height="17"><path d="M15 6l-6 6 6 6" /></svg>
          Back
        </button>

        {err && <div className="pd-err">{err}</div>}

        <div className="world-grid">
          {/* LEFT — a true two-faced create-style flip (no Framer layout):
              · .world-card  = outer wrapper, takes the POSITION FLIP (translate/
                scale from the clicked card's rect) — see wrapRef + the effect.
              · .world-flip  = preserve-3d container, takes the ROTATION. At rest
                it shows the BACK (rotateY 180°, via the CSS class — persists after
                the inline cleanup); on entry it starts at 0° (front) and plays to
                180° to reveal the editorial back.
              · two faces, each backface-hidden: FRONT = the same carousel art for
                this pact; BACK = the editorial <CardBack/> (pre-rotated 180°). */}
          <div ref={wrapRef} className="world-card">
            <div ref={flipRef} className={`world-flip${entering ? "" : " world-flip--rest"}`}>
              <div className="world-face world-face-front">
                {cbArt.kind === "photo" ? (
                  <CustomCardFront imageSrc={cbArt.src} title={cbArt.title} />
                ) : cbArt.kind === "art" ? (
                  <img className="world-front-art" src={cbArt.src} alt={pact.title} draggable={false} />
                ) : (
                  <div className="world-front-glyph">
                    <GoalGlyph title={pact.title} size={48} />
                    <div className="world-front-glyph-title">{pact.title}</div>
                  </div>
                )}
              </div>
              <div className="world-face world-face-back">
                <CardBack
                  goalName={pact.title}
                  days={days}
                  weeks={weeks}
                  weeksWord={weeksWord}
                  stake={pact.stake_amount_cents / 100}
                  charity={cbCharity}
                  agent={cbAgent}
                  owner={pact.signer_name || pact.owner}
                  sealedDate={sealedDate}
                  titleReady
                  freqReady
                  stakeReady
                  charityReady
                  agentReady
                  signed
                  zoneState={() => "done"}
                />
              </div>
            </div>
          </div>

          {/* RIGHT — status-keyed panel. */}
          <div className="world-panel">{panelForStatus()}</div>
        </div>
      </div>

      {/* ── Overlays / modals ── */}
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

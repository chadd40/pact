import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { GrainGradient } from "@paper-design/shaders-react";
import { Create } from "./Create";
import { LandingLogoMenu, PACT_DOWNLOAD_URL, type LandingMenuTarget } from "../components/LandingLogoMenu";
import { asset } from "../lib/asset";
import "./landing.css";

// The wishes that cycle through the blue bubble + drift in the background.
const GOALS = [
  "worked out more",
  "meditated more",
  "drank less",
  "read more",
  "used my phone less",
  "doomscrolled less",
  "shipped something every day",
];

// Ambient wishes that drift up + fade across the whole hero. Positioned mostly in
// the left/right margins (% → scales with the window) so they frame the centered
// phone, with a few up top / down low to fill the field.
const DRIFT: Array<{ t: string; pos: React.CSSProperties; d: string; dur: string }> = [
  // left column
  { t: "I wish I read more", pos: { left: "6%", top: "16%" }, d: "0s", dur: "14s" },
  { t: "I wish I called my mom", pos: { left: "4%", top: "35%" }, d: "5s", dur: "16s" },
  { t: "I wish I drank less", pos: { left: "8%", top: "54%" }, d: "3.2s", dur: "15s" },
  { t: "I wish I journaled", pos: { left: "5%", top: "73%" }, d: "6.8s", dur: "15s" },
  { t: "I wish I doomscrolled less", pos: { left: "15%", bottom: "8%" }, d: "2.4s", dur: "13s" },
  { t: "I wish I woke up early", pos: { left: "19%", top: "25%" }, d: "8.1s", dur: "17s" },
  { t: "I wish I cooked more", pos: { left: "12%", bottom: "26%" }, d: "4.7s", dur: "14s" },
  // right column
  { t: "I wish I meditated more", pos: { right: "6%", top: "18%" }, d: "1.2s", dur: "13s" },
  { t: "I wish I worked out more", pos: { right: "5%", top: "37%" }, d: "3.6s", dur: "14s" },
  { t: "I wish I shipped more", pos: { right: "9%", top: "55%" }, d: "6s", dur: "17s" },
  { t: "I wish I slept earlier", pos: { right: "5%", top: "74%" }, d: "4.4s", dur: "15s" },
  { t: "I wish I stretched daily", pos: { right: "16%", bottom: "9%" }, d: "7.3s", dur: "13s" },
  { t: "I wish I saved more", pos: { right: "19%", top: "27%" }, d: "2.1s", dur: "16s" },
  { t: "I wish I touched grass", pos: { right: "12%", bottom: "27%" }, d: "9.2s", dur: "15s" },
  // top edges, framing the headline
  { t: "I wish I wrote more", pos: { left: "29%", top: "9%" }, d: "5.6s", dur: "16s" },
  { t: "I wish I learned guitar", pos: { right: "28%", top: "11%" }, d: "1.9s", dur: "14s" },
];

// The scroll-revealed iMessage script. `side` says who's "composing" it — an
// incoming line ("in") shows the friend's typing dots first; an outgoing line
// ("out") gets typed into the composer, then sent.
type Side = "in" | "out";
const SIDES: Side[] = ["in", "out", "in", "out", "in", "out", "in", "in", "out", "in", "out", "in", "in"];
const MSG_COUNT = SIDES.length;

// Map scroll progress (0..1) through the pinned hero to how many messages should
// be revealed. The first two (friend's opener + your wish) are up at the top.
function targetFor(p: number): number {
  if (p < 0.08) return 2;
  if (p < 0.15) return 3;
  if (p < 0.22) return 4;
  if (p < 0.3) return 5;
  if (p < 0.38) return 6;
  if (p < 0.46) return 7; // headline flips here (the pact lands); the rest is dwell so it can be read
  if (p < 0.54) return 8;
  if (p < 0.62) return 9;
  if (p < 0.7) return 10;
  if (p < 0.78) return 11;
  if (p < 0.87) return 12;
  return 13;
}

// The iPhone status-bar clock — the viewer's local time, iOS-style (h:mm, no AM/PM).
function phoneTime(): string {
  const d = new Date();
  const h = d.getHours() % 12 || 12;
  return `${h}:${d.getMinutes().toString().padStart(2, "0")}`;
}

export function Landing() {
  const navigate = useNavigate();
  const location = useLocation();
  // The link / cards all lead into the new-user onboarding (create → link agent → link Link).
  const onboard = () => navigate("/create");

  const pinRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const stageWrapRef = useRef<HTMLDivElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);

  const [revealed, setRevealed] = useState(0); // # of messages shown
  const [phase, setPhase] = useState<"idle" | "in" | "out">("idle"); // pre-reveal beat
  const [target, setTarget] = useState(2); // scroll-driven reveal target
  const [goal, setGoal] = useState(0); // cycling wish
  const [clock, setClock] = useState(phoneTime);

  const revealedRef = useRef(0);
  revealedRef.current = revealed;

  const payoff = revealed >= 7; // headline crossfades once "you make a pact" lands

  // Keep the phone clock on the viewer's current local time.
  useEffect(() => {
    const id = setInterval(() => setClock(phoneTime()), 15000);
    return () => clearInterval(id);
  }, []);

  // Scale the phone scene (phone + cue) as ONE fixed-size design stage to fit the
  // space below the headline — uniform zoom.
  useEffect(() => {
    const STAGE_W = 480;
    const STAGE_H = 770;
    const BOTTOM_SAFE = 16; // always keep the phone clear of the bottom edge
    const fit = () => {
      const wrap = stageWrapRef.current;
      const availH = (wrap?.clientHeight ?? window.innerHeight) - BOTTOM_SAFE;
      const availW = wrap?.clientWidth ?? window.innerWidth;
      const s = Math.max(0.3, Math.min(availW / STAGE_W, availH / STAGE_H, 1.2));
      if (stageRef.current) stageRef.current.style.transform = `scale(${s.toFixed(3)})`;
    };
    fit();
    const raf = requestAnimationFrame(fit);
    const t1 = setTimeout(fit, 80);
    const t2 = setTimeout(fit, 320);
    window.addEventListener("resize", fit);
    window.addEventListener("orientationchange", fit);
    // Observe the stage's own container (most reliable) plus the document, so the
    // phone re-fits on any window or layout change, not just full reloads.
    const ro = new ResizeObserver(fit);
    if (stageWrapRef.current) ro.observe(stageWrapRef.current);
    ro.observe(document.documentElement);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(t1);
      clearTimeout(t2);
      window.removeEventListener("resize", fit);
      window.removeEventListener("orientationchange", fit);
      ro.disconnect();
    };
  }, []);

  // Scroll: progress through the tall pinned section drives the reveal target.
  useEffect(() => {
    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const pin = pinRef.current;
        if (!pin) return;
        const vh = window.innerHeight;
        const y = window.scrollY || 0;
        const p = Math.min(1, Math.max(0, (y - pin.offsetTop) / Math.max(1, pin.offsetHeight - vh)));
        setTarget(targetFor(p));
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Reveal stepper: walk `revealed` toward `target`, one message at a time, with a
  // typing beat before each. Scrolling back up snaps instantly (no reverse play).
  useEffect(() => {
    if (revealed === target) return;
    if (revealed > target) {
      setRevealed(target);
      setPhase("idle");
      return;
    }
    // Far behind (fast scroll): snap most, animate only the final one.
    if (target - revealed > 1) {
      setPhase("idle");
      setRevealed(target - 1);
      return;
    }
    // Exactly one to go — play its typing beat, then land the bubble.
    const side = SIDES[revealed];
    setPhase(side);
    const dur = side === "in" ? 760 : 620;
    const id = window.setTimeout(() => {
      setRevealed((r) => Math.min(MSG_COUNT, r + 1));
      setPhase("idle");
    }, dur);
    return () => window.clearTimeout(id);
  }, [target, revealed]);

  // Cycle the wish only while it's the live bubble at the top.
  useEffect(() => {
    const iv = setInterval(() => {
      if (revealedRef.current <= 2) setGoal((g) => (g + 1) % GOALS.length);
    }, 1900);
    return () => clearInterval(iv);
  }, []);

  // Fade-up sections as they enter the viewport.
  useEffect(() => {
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && e.target.classList.add("is-in")),
      { threshold: 0.12 }
    );
    document.querySelectorAll(".landing [data-reveal]").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);

  // Keep the thread pinned to the newest message as beats land.
  useEffect(() => {
    const m = threadRef.current;
    if (m) m.scrollTop = m.scrollHeight;
  }, [revealed, phase, goal]);

  const goTo = (id: LandingMenuTarget) => {
    if (id === "top") {
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const scrollTarget = (location.state as { scrollTo?: LandingMenuTarget } | null)?.scrollTo;
  useEffect(() => {
    if (!scrollTarget) return;
    const id = window.setTimeout(() => goTo(scrollTarget), 0);
    return () => window.clearTimeout(id);
  }, [scrollTarget]);

  // What's being typed into the composer right now (outgoing beat).
  const composing = phase === "out";
  const composeText =
    revealed === 1
      ? `ehh… I wish I ${GOALS[goal]}`
      : revealed === 3
        ? "ok ok i know 😩"
        : revealed === 5
          ? "wait how does it work"
          : revealed === 8
            ? "ok but will i actually stick to it 😅"
            : revealed === 10
              ? "ok i'm in, how do i start"
              : "";

  return (
    <div className="landing">
      {/* ── Fixed chrome · logo dropdown nav ─────────────────────────────────── */}
      <LandingLogoMenu onGoTo={goTo} />

      {/* ── Act 1–3 · pinned phone, scroll-revealed conversation ─────────────── */}
      <div className="lp-pin" ref={pinRef}>
        <div className="lp-sticky">
          {/* Animated watercolor-on-paper shader behind the phone (Paper Design). */}
          <div className="lp-shader" aria-hidden="true">
            <GrainGradient
              style={{ width: "100%", height: "100%" }}
              colorBack="#efe6d3"
              colors={["#f5edda", "#ecdfc8", "#e6d1b6", "#e0c2a2", "#d8c6a8"]}
              softness={0.9}
              intensity={0.24}
              noise={0.13}
              shape="blob"
              speed={0.5}
              scale={1.2}
            />
          </div>
          {/* ambient drifting wishes (scale with the window) */}
          <div className="lp-field" aria-hidden="true">
            {DRIFT.map((w, i) => (
              <span
                key={i}
                className="lp-drift"
                style={{ ...w.pos, animationDelay: w.d, animationDuration: w.dur }}
              >
                <span className="lp-drift-t">{w.t}</span>
              </span>
            ))}
            <span className="lp-drift lp-sparkle" style={{ left: "15%", top: "22%", animationDelay: "1.8s" }}>
              ✦
            </span>
            <span className="lp-drift lp-sparkle" style={{ right: "14%", top: "34%", animationDelay: "4.2s" }}>
              ✦
            </span>
          </div>

          {/* headline — crossfades between the two states on scroll */}
          <div className="lp-headline">
            <span className={"lp-headline-line" + (!payoff ? " on" : "")}>
              Everyone has a list of things they wish they did.
            </span>
            <span className={"lp-headline-line" + (payoff ? " on" : "")}>
              Now your agent can keep you accountable with a pact.
            </span>
          </div>

          {/* phone scene — scales as one unit to fill the space below the headline */}
          <div className="lp-stagewrap" ref={stageWrapRef}>
            <div className="lp-stage" ref={stageRef}>
              <div className="lp-bezel">
                <div className="lp-screen">
                  <div className="lp-statusbar">
                    <span className="lp-time">{clock}</span>
                    <span className="lp-status-right">
                      <span className="lp-signal">
                        <i /> <i /> <i /> <i />
                      </span>
                      <span className="lp-5g m">5G</span>
                      <span className="lp-batt">
                        <span />
                      </span>
                    </span>
                  </div>
                  <div className="lp-island" />

                  <div className="lp-imhead">
                    <span className="lp-imback">‹</span>
                    <img src={asset("/alfie.png")} alt="friend" className="lp-imavatar" />
                    <span className="lp-imname">
                      friend <span className="lp-imchevron">›</span>
                    </span>
                  </div>

                  <div className="lp-thread" ref={threadRef}>
                    <div className="lp-daystamp">
                      <b>Today</b> {clock} {new Date().getHours() < 12 ? "AM" : "PM"}
                    </div>

                    {revealed > 0 && <div className="lp-msg lp-in">how'd the week actually go 👀</div>}

                    {revealed > 1 && (
                      <div className="lp-msg lp-out lp-wishbubble">
                        ehh… I wish I{" "}
                        <span key={goal} className="lp-wishword">
                          {GOALS[goal]}
                        </span>
                      </div>
                    )}

                    {revealed > 2 && <div className="lp-msg lp-in">you said that last week 😭</div>}
                    {revealed > 3 && <div className="lp-msg lp-out">ok ok i know 😩</div>}
                    {revealed > 4 && <div className="lp-msg lp-in">your agent can actually help with that now</div>}
                    {revealed > 5 && <div className="lp-msg lp-out">wait how does it work</div>}
                    {revealed > 6 && <div className="lp-msg lp-in">you make a pact with it 🤝</div>}
                    {revealed > 7 && (
                      <div className="lp-msg lp-in">if you flake, then it donates what you staked to charity automatically</div>
                    )}
                    {revealed > 8 && <div className="lp-msg lp-out">ok but will i actually stick to it 😅</div>}
                    {revealed > 9 && (
                      <div className="lp-msg lp-in">it's on you all week. nudges you, you send proof 📸</div>
                    )}
                    {revealed > 10 && <div className="lp-msg lp-out">ok i'm in, how do i start</div>}
                    {revealed > 11 && (
                      <div className="lp-msg lp-in">go here, then run /pact with your agent 👇</div>
                    )}
                    {revealed > 12 && (
                      <div className="lp-card-wrap">
                        <button className="lp-richlink" onClick={onboard}>
                          <div className="lp-richlink-hero">
                            <span className="lp-richlink-sheen" />
                            <img src={asset("/pact_icon.png")} alt="" className="lp-richlink-icon" />
                          </div>
                          <div className="lp-richlink-foot">
                            <div className="lp-richlink-title">Make a promise you actually keep</div>
                            <div className="lp-richlink-url">pact.new</div>
                          </div>
                        </button>
                      </div>
                    )}

                    {/* friend's typing dots — plays right before each incoming line */}
                    {phase === "in" && (
                      <div className="lp-msg lp-typing" aria-hidden="true">
                        <span /> <span /> <span />
                      </div>
                    )}
                  </div>

                  <div className={"lp-composer" + (composing ? " is-typing" : "")}>
                    <span className="lp-plus">+</span>
                    <span className={"lp-input" + (composing ? " typing" : "")}>
                      {composing ? composeText : "iMessage"}
                    </span>
                    <span className={"lp-send" + (composing ? " armed" : "")}>↑</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── What a pact is · animated bento ──────────────────────────────────── */}
      <section className="lp-section lp-how">
        <div className="lp-wrap">
          <div className="lp-sec-head" data-reveal>
            <div className="lp-eyebrow m">What a pact is</div>
            <h2 className="lp-sec-title">A promise that actually costs something to break.</h2>
          </div>

          <div className="lp-bento">
            {/* CREATE — a flatter fan of the real cards filling the top */}
            <article className="lp-cell bento-create" data-reveal>
              <div className="bento-visual bv-fan" aria-hidden="true">
                <img className="bf-card bf-1" src={asset("/cards/meditate.svg")} alt="" draggable={false} />
                <img className="bf-card bf-2" src={asset("/cards/read.svg")} alt="" draggable={false} />
                <img className="bf-card bf-3" src={asset("/cards/workout.svg")} alt="" draggable={false} />
                <img className="bf-card bf-4" src={asset("/cards/ship.svg")} alt="" draggable={false} />
                <img className="bf-card bf-5" src={asset("/cards/nophone.svg")} alt="" draggable={false} />
              </div>
              <div className="bento-foot">
                <div className="bento-h">Create a pact</div>
                <p className="bento-p">Pick the thing you keep wishing you'd do, browse the deck, or create your own pact.</p>
              </div>
            </article>

            {/* AGENT — Hermes, cheering you on, in a lighter chat panel (the heart of it) */}
            <article className="lp-cell bento-agent" data-reveal style={{ transitionDelay: ".06s" }}>
              <div className="ba-panel">
                <div className="ba-top">
                  <img className="ba-av" src={asset("/agents/Hermes.svg")} alt="Hermes" />
                  <div>
                    <div className="ba-name">Hermes</div>
                    <div className="ba-status">
                      <span className="ba-dot" /> in your corner
                    </div>
                  </div>
                </div>
                <div className="ba-thread">
                  <div className="ba-bubble b1">12 hours left to log today's workout ⏳</div>
                  <div className="ba-bubble b2">You're 4 for 5 this week, way ahead of last week.</div>
                  <div className="ba-bubble b3">One session and the week is clean. Don't hand $200 to charity tonight 💪</div>
                  <div className="ba-typing" aria-hidden="true">
                    <span /> <span /> <span />
                  </div>
                </div>
                <div className="ba-composer" aria-hidden="true">
                  <span className="ba-field">Message Hermes…</span>
                  <span className="ba-send">↑</span>
                </div>
              </div>
              <div className="bento-foot">
                <div className="bento-h">An agent in your corner</div>
                <p className="bento-p">
                  Hermes checks your proof, remembers your streak, and talks you through the days you'd rather skip.
                </p>
              </div>
            </article>

            {/* STAKE — a Link card swiped across a reader */}
            <article className="lp-cell bento-stake" data-reveal style={{ transitionDelay: ".12s" }}>
              <div className="bento-visual bv-stake" aria-hidden="true">
                <div className="bs-reader">
                  <div className="bs-card">
                    <img className="bs-card-logo" src={asset("/link_logo.svg")} alt="" />
                    <div className="bs-card-amt m">$200</div>
                  </div>
                  <div className="bs-terminal">
                    <div className="bs-slot" />
                    <div className="bs-ok">✓</div>
                  </div>
                </div>
              </div>
              <div className="bento-foot">
                <div className="bento-h">Stake it</div>
                <p className="bento-p">Put your money behind it through our Link integration. Miss your goal and your agent is donating to charity.</p>
              </div>
            </article>

            {/* PROVE — drop a photo, it gets checked, then stamped */}
            <article className="lp-cell bento-prove" data-reveal style={{ transitionDelay: ".18s" }}>
              <div className="bento-visual bv-prove" aria-hidden="true">
                <div className="bp-zone">
                  <div className="bp-file">
                    <img className="bp-thumb" src={asset("/create_3.png")} alt="" />
                    <span className="bp-fname m">piano.jpg</span>
                  </div>
                  <div className="bp-status">
                    <div className="bp-check">
                      <span className="bp-spin" />
                      <span className="bp-checking m">Checking you played the piano…</span>
                    </div>
                    <div className="bp-stamp">
                      <svg viewBox="0 0 24 24" width="14" height="14">
                        <path d="M5 13l4 4L19 7" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      Verified
                    </div>
                  </div>
                </div>
              </div>
              <div className="bento-foot">
                <div className="bento-h">Prove it</div>
                <p className="bento-p">Snap a photo or screenshot. Your agent reads it, confirms you hit your goal, and logs the win.</p>
              </div>
            </article>
          </div>
        </div>
      </section>

      {/* ── The deck · the real create flow, embedded ────────────────────────── */}
      <section className="lp-section lp-deck-sec" id="deck">
        <div className="lp-deck-sticky">
          <div className="lp-wrap lp-deck-head" data-reveal>
            <div className="lp-eyebrow m">Get started today</div>
            <h2 className="lp-sec-title">Make your first pact.</h2>
            <p className="lp-coach-lede lp-deck-lede">
              This is the real thing. Browse the deck, pick a card, and shape it into a pact right here.
            </p>
          </div>
          <div className="lp-embed-deck">
            <Create embedded />
          </div>
        </div>
        {/* Mobile fallback — the deck is desktop-only, so don't leave a void. */}
        <div className="lp-deck-mobilecta">
          <p>The deck is built for a bigger screen. Open Pact on a laptop to deal yourself in.</p>
          <button className="lp-deck-cta" onClick={onboard}>
            Make your first pact <span>→</span>
          </button>
        </div>
      </section>

      {/* ── Integrations (dark tail begins) ──────────────────────────────────── */}
      <section className="lp-section lp-integrations" id="integrations">
        <div className="lp-wrap">
          <div className="lp-sec-head dark" data-reveal>
            <div className="lp-eyebrow m">Integrations</div>
            <h2 className="lp-sec-title">Bring your own agent.</h2>
            <p className="lp-int-lede">
              Pact ships as a skill, so it runs right inside the agent you already use instead of asking you to learn a
              new one. Hermes is built in and recommended, Claude Code is one connect away, and anywhere else your
              skills run, Pact runs.
            </p>
          </div>
          <div className="lp-int-grid">
            <div className="lp-int-card lp-int-primary" data-reveal>
              <span className="lp-int-logo">
                <img src={asset("/agents/Hermes.svg")} alt="Hermes" />
              </span>
              <div className="lp-int-name">Hermes</div>
              <div className="lp-int-sub">Built in · ready the moment you seal</div>
              <span className="lp-int-tag m on">Recommended</span>
            </div>
            <div className="lp-int-card" data-reveal style={{ transitionDelay: ".06s" }}>
              <span className="lp-int-logo">
                <img src={asset("/agents/Claude.svg")} alt="Claude Code" />
              </span>
              <div className="lp-int-name">Claude Code</div>
              <div className="lp-int-sub">Straight from your dev workflow</div>
              <span className="lp-int-tag m">Connect</span>
            </div>
            <div className="lp-int-card" data-reveal style={{ transitionDelay: ".12s" }}>
              <span className="lp-int-logo">
                <img src={asset("/agents/Nemoclaw.svg")} alt="NVIDIA" />
              </span>
              <div className="lp-int-name">NVIDIA</div>
              <div className="lp-int-sub">NeMo agents, via API</div>
              <span className="lp-int-tag m">Connect</span>
            </div>
            <div className="lp-int-card" data-reveal style={{ transitionDelay: ".18s" }}>
              <span className="lp-int-logo">
                <svg viewBox="0 0 24 24" fill="none" stroke="#2e2a20" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="26" height="26" aria-hidden="true">
                  <circle cx="12" cy="12" r="9" />
                  <path d="M3 12h18" />
                  <path d="M12 3c2.6 2.6 2.6 15.4 0 18M12 3c-2.6 2.6-2.6 15.4 0 18" />
                </svg>
              </span>
              <div className="lp-int-name">Anywhere skills run</div>
              <div className="lp-int-sub">If your agent loads skills, it loads Pact</div>
              <span className="lp-int-tag m on">Available</span>
            </div>
          </div>
        </div>
      </section>

      {/* ── FAQ (answers "what is a pact") ───────────────────────────────────── */}
      <section className="lp-section lp-faq" id="faq">
        <div className="lp-wrap lp-faq-wrap">
          <div className="lp-faq-head" data-reveal>
            <div className="lp-eyebrow m">FAQ</div>
            <h2 className="lp-sec-title">What is a pact, exactly?</h2>
          </div>
          <div className="lp-faq-list">
            {FAQS.map((f, i) => (
              <details className="lp-faq-item" key={f.q} data-reveal style={{ transitionDelay: `${0.04 * i}s` }}>
                <summary>
                  <span>{f.q}</span>
                  <span className="lp-faq-plus" aria-hidden="true" />
                </summary>
                <p>{f.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* ── Final CTA ────────────────────────────────────────────────────────── */}
      <section className="lp-section lp-final">
        <img className="lp-final-dot" src={asset("/dot.svg")} alt="" aria-hidden="true" />
        <h2 className="lp-final-title">Become the better version of yourself.</h2>
        <p className="lp-final-sub">
          One promise. Real stakes. An agent in your corner. It starts the moment you stop wishing.
        </p>
        <button className="lp-final-cta" onClick={onboard}>
          Make your first pact <span>→</span>
        </button>
      </section>

      {/* ── Footer · the big cut-off wordmark ────────────────────────────────── */}
      <footer className="lp-bigfoot">
        <div className="lp-bigfoot-links">
          <button onClick={() => goTo("top")}>Home</button>
          <a href={PACT_DOWNLOAD_URL} target="_blank" rel="noreferrer">
            Download
          </a>
          <span className="lp-bigfoot-copy m">Put it on the line · ✦ · 2026</span>
        </div>
        <div className="lp-bigfoot-mark" aria-hidden="true">
          pact
        </div>
      </footer>
    </div>
  );
}

const FAQS: Array<{ q: string; a: string }> = [
  {
    q: "What is a pact?",
    a: "A pact is a promise you put real money behind. You pick a goal, set how often and for how many weeks you'll show up, and stake anywhere from $10 to $500. Your agent coaches you the whole way and checks your proof at each check-in. Show up enough times and you keep every dollar. Fall short by the deadline and your stake goes to a charity you chose when you made the pact.",
  },
  {
    q: "Where does the money go if I fail?",
    a: "To one of fifteen real causes you choose when you create the pact, like the World Wildlife Fund, charity: water, Save the Children, or Doctors Without Borders. Pact never keeps your stake and never takes a cut. The money only ever moves to your chosen charity, and only if you don't follow through. Hit your goal and nothing is charged at all.",
  },
  {
    q: "Does Pact hold my money?",
    a: "No. Pact is charge-on-fail, never an escrow or a hold. Connecting Link simply registers a funding source so the stake is ready if you ever need it, and your real money stays in your account until you actually miss. Even then it's a single, capped charge that goes straight to your charity, never to Pact.",
  },
  {
    q: "How does Pact know I actually did it?",
    a: "At each check-in you submit proof: a photo, a screenshot, a link, a file, or a short note. Your agent reads it against the goal you set and logs the result. To keep things honest, photos have their metadata stripped and Pact checks for near-duplicate images so you can't reuse the same shot twice. It's a best-effort honesty check, not a forensic investigation, so the point is to keep you accountable rather than to interrogate you.",
  },
  {
    q: "What happens if I miss for a real reason?",
    a: "Missing doesn't fire an instant charge. When a pact comes up short, a dispute window opens, twenty-four hours by default, where you can add more proof or let a borderline check-in get a second look. If that turns it around, the pact succeeds and nothing is charged. Only if the window closes with you still short does the donation go through, and your agent never moves money quietly on its own.",
  },
  {
    q: "What kinds of goals work best?",
    a: "Anything you can show up for on a regular cadence and prove in a quick photo, screenshot, link, or note. Think workouts, daily writing, language practice, reading, sketching, shipping code, or getting to bed on time. You choose how many days a week and how many weeks, and Pact counts at most one check-in per day, so it rewards consistency over one heroic sprint. If you can describe what done looks like, your agent can verify it.",
  },
  {
    q: "Can I bring my own agent?",
    a: "Yes, that's the whole idea. Pact ships as a skill, so it loads right into the agent you already use instead of forcing you into a new app. Hermes is built in and recommended, Claude Code is one connect away, and any agent that loads skills can run Pact. Agents that speak MCP can connect over Pact's local server instead. Whichever you pick, your agent does the coaching and the proof-checking while Pact supplies the rules and keeps the receipts.",
  },
  {
    q: "How do I start?",
    a: "Making a pact takes about a minute: pick a goal or a template, set your cadence and length, choose a stake from $10 to $500, pick your charity and your agent, and sign the card. You don't need an account, a password, or any billing info to seal one. To put real money on the line, download the free Mac app and connect Link during onboarding, which registers a funding source without charging anything. From there your agent keeps you honest, and your money only moves if you don't.",
  },
];

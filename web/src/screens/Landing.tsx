import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
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

// Ambient wishes that drift up + fade across the whole hero. Positioned in the
// left/right margins (% → scales with the window) so they clear the centered phone.
const DRIFT: Array<{ t: string; pos: React.CSSProperties; d: string; dur: string }> = [
  { t: "I wish I read more", pos: { left: "7%", bottom: "20%" }, d: "0s", dur: "14s" },
  { t: "I wish I doomscrolled less", pos: { left: "18%", bottom: "9%" }, d: "2.4s", dur: "13s" },
  { t: "I wish I called my mom", pos: { left: "10%", top: "30%" }, d: "5s", dur: "16s" },
  { t: "I wish I drank less", pos: { left: "23%", top: "15%" }, d: "3.2s", dur: "15s" },
  { t: "I wish I meditated more", pos: { right: "15%", bottom: "15%" }, d: "1.2s", dur: "13s" },
  { t: "I wish I worked out more", pos: { right: "24%", bottom: "25%" }, d: "3.6s", dur: "14s" },
  { t: "I wish I shipped more", pos: { right: "8%", top: "27%" }, d: "6s", dur: "17s" },
  { t: "I wish I slept earlier", pos: { right: "20%", top: "13%" }, d: "4.4s", dur: "15s" },
];

// The iPhone status-bar clock — the viewer's local time, iOS-style (h:mm, no AM/PM).
function phoneTime(): string {
  const d = new Date();
  const h = d.getHours() % 12 || 12;
  return `${h}:${d.getMinutes().toString().padStart(2, "0")}`;
}

export function Landing() {
  const navigate = useNavigate();
  // The link / cards all lead into the new-user onboarding (create → link agent → link Link).
  const onboard = () => navigate("/create");

  const pinRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const stageWrapRef = useRef<HTMLDivElement>(null);
  const cueRef = useRef<HTMLDivElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const beatRef = useRef(0);

  const [beat, setBeat] = useState(0); // 0..3 — how far the conversation has revealed
  const [showTyping, setShowTyping] = useState(false);
  const [showYou, setShowYou] = useState(false);
  const [goal, setGoal] = useState(0);
  const [clock, setClock] = useState(phoneTime);

  // Keep the phone clock on the viewer's current local time.
  useEffect(() => {
    const id = setInterval(() => setClock(phoneTime()), 15000);
    return () => clearInterval(id);
  }, []);

  // Intro: "you" type for a beat, then the wish bubble lands.
  useEffect(() => {
    const t1 = setTimeout(() => setShowTyping(true), 650);
    const t2 = setTimeout(() => {
      setShowTyping(false);
      setShowYou(true);
    }, 1650);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, []);

  // Scale the phone scene (phone + cue) as ONE fixed-size design stage to fit the
  // space below the headline — uniform zoom. Measures the actual available height
  // so the headline + chrome are always cleared.
  useEffect(() => {
    const STAGE_W = 480;
    const STAGE_H = 770;
    const fit = () => {
      const availH = stageWrapRef.current?.clientHeight || window.innerHeight;
      const s = Math.min(window.innerWidth / STAGE_W, availH / STAGE_H, 1.2);
      if (stageRef.current) stageRef.current.style.transform = `scale(${s.toFixed(3)})`;
    };
    fit();
    const raf = requestAnimationFrame(fit);
    const t1 = setTimeout(fit, 80);
    const t2 = setTimeout(fit, 320);
    window.addEventListener("resize", fit);
    const ro = new ResizeObserver(fit);
    ro.observe(document.documentElement);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(t1);
      clearTimeout(t2);
      window.removeEventListener("resize", fit);
      ro.disconnect();
    };
  }, []);

  // Scroll: progress through the tall pinned section drives the conversation beats.
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
        const b = p < 0.14 ? 0 : p < 0.42 ? 1 : p < 0.7 ? 2 : 3;
        beatRef.current = b;
        setBeat(b);
        if (cueRef.current) cueRef.current.style.opacity = y > 30 || p > 0.02 ? "0" : "1";
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Cycle the wish only while we're at the top (beat 0) and the bubble is up.
  useEffect(() => {
    const iv = setInterval(() => {
      if (beatRef.current === 0 && showYou) setGoal((g) => (g + 1) % GOALS.length);
    }, 1900);
    return () => clearInterval(iv);
  }, [showYou]);

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
  }, [beat, showYou, showTyping, goal]);

  return (
    <div className="landing">
      {/* ── Fixed chrome ─────────────────────────────────────────────────── */}
      <div className="lp-chrome">
        <img src="/primary_logo.svg" alt="Pact" className="lp-logo" />
      </div>

      {/* ── Act 1–3 · pinned phone, scroll-revealed conversation ─────────────── */}
      <div className="lp-pin" ref={pinRef}>
        <div className="lp-sticky">
          {/* ambient drifting wishes (scale with the window) */}
          <div className="lp-field" aria-hidden="true">
            {DRIFT.map((w, i) => (
              <span
                key={i}
                className="lp-drift"
                style={{ ...w.pos, animationDelay: w.d, animationDuration: w.dur }}
              >
                {w.t}
              </span>
            ))}
            <span className="lp-drift lp-sparkle" style={{ left: "15%", top: "22%", animationDelay: "1.8s" }}>
              ✦
            </span>
            <span className="lp-drift lp-sparkle" style={{ right: "14%", top: "34%", animationDelay: "4.2s" }}>
              ✦
            </span>
          </div>

          {/* headline — swaps to the payoff line once the last message lands */}
          <div className="lp-headline">
            <span key={beat >= 3 ? "after" : "before"} className="lp-headline-text">
              {beat >= 3
                ? "Now your agent can keep you accountable with a pact."
                : "Everyone has a list of things they wish they did."}
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
                <img src="/alfie.png" alt="friend" className="lp-imavatar" />
                <span className="lp-imname">
                  friend <span className="lp-imchevron">›</span>
                </span>
              </div>

              <div className="lp-thread" ref={threadRef}>
                <div className="lp-daystamp">
                  <b>Today</b> {clock} {new Date().getHours() < 12 ? "AM" : "PM"}
                </div>

                <div className="lp-msg lp-in">how'd the week actually go 👀</div>

                {showTyping && (
                  <div className="lp-msg lp-typing">
                    <span /> <span /> <span />
                  </div>
                )}
                {showYou && (
                  <div className="lp-msg lp-out lp-wishbubble">
                    ehh… I wish I{" "}
                    <span key={goal} className="lp-wishword">
                      {GOALS[goal]}
                    </span>
                  </div>
                )}

                {beat >= 1 && (
                  <>
                    <div className="lp-msg lp-in">you said that last week 😭</div>
                    <div className="lp-msg lp-out">ok ok i know 😩</div>
                  </>
                )}

                {beat >= 2 && (
                  <>
                    <div className="lp-msg lp-in">your agent can help with that now</div>
                    <div className="lp-msg lp-in">
                      <span className="lp-link">pact.new</span>
                    </div>
                  </>
                )}

                {beat >= 3 && (
                  <>
                    <div className="lp-card-wrap">
                      <button className="lp-richlink" onClick={onboard}>
                        <div className="lp-richlink-hero">
                          <img src="/pact_icon.png" alt="" className="lp-richlink-icon" />
                        </div>
                        <div className="lp-richlink-foot">
                          <div className="lp-richlink-title">Make a promise you actually keep</div>
                          <div className="lp-richlink-url">pact.new</div>
                        </div>
                      </button>
                    </div>
                    <div className="lp-msg lp-in lp-after">
                      put money on it. then you'll actually show up 💪
                    </div>
                  </>
                )}
              </div>

              <div className="lp-composer">
                <span className="lp-plus">+</span>
                <span className="lp-input">iMessage</span>
                <span className="lp-send">↑</span>
              </div>
              <div className="lp-homebar" />
            </div>
          </div>

              <div className="lp-cue" ref={cueRef}>
                <span className="m">Scroll</span>
                <span className="lp-cue-arrow">↓</span>
              </div>
            </div>
          </div>

        </div>
      </div>

      {/* ── How it works · bento ─────────────────────────────────────────────── */}
      <section className="lp-section lp-how">
        <div className="lp-wrap">
          <div className="lp-sec-head" data-reveal>
            <div className="lp-eyebrow m">What a pact is</div>
            <h2 className="lp-sec-title">A promise that actually costs something to break.</h2>
          </div>
          <div className="lp-bento">
            <article className="lp-bento-card" data-reveal>
              <div className="lp-bento-no m">01</div>
              <div className="lp-bento-ico">{ICON.target}</div>
              <div className="lp-bento-h">Create a pact</div>
              <p className="lp-bento-p">Pick the thing you keep wishing you'd do — how often, for how long.</p>
            </article>
            <article className="lp-bento-card" data-reveal style={{ transitionDelay: ".08s" }}>
              <div className="lp-bento-no m">02</div>
              <div className="lp-bento-ico">{ICON.coin}</div>
              <div className="lp-bento-h">Stake it</div>
              <p className="lp-bento-p">Put real money behind it. Enough that skipping a day stings.</p>
            </article>
            <article className="lp-bento-card" data-reveal style={{ transitionDelay: ".16s" }}>
              <div className="lp-bento-no m">03</div>
              <div className="lp-bento-ico">{ICON.camera}</div>
              <div className="lp-bento-h">Prove it</div>
              <p className="lp-bento-p">Snap a photo or screenshot. Your agent verifies it in seconds.</p>
            </article>
            {/* PRIMARY — the agentic coaching piece */}
            <article className="lp-bento-card lp-bento-primary" data-reveal style={{ transitionDelay: ".24s" }}>
              <div className="lp-bento-no m">04</div>
              <div className="lp-bento-ico lp-bento-ico-accent">{ICON.spark}</div>
              <div className="lp-bento-h">An agent in your corner</div>
              <p className="lp-bento-p">
                Hermes, built in, or your own — it checks your proof, remembers your streak, and
                talks you through the days you'd rather skip.
              </p>
              <div className="lp-bento-badge m">The heart of it</div>
            </article>
          </div>
        </div>
      </section>

      {/* ── Coaching spotlight ──────────────────────────────────────────────── */}
      <section className="lp-section lp-coach-sec">
        <div className="lp-wrap lp-coach-grid">
          <div className="lp-coach-copy" data-reveal>
            <div className="lp-eyebrow m">Who keeps you honest</div>
            <h2 className="lp-sec-title">You won't be doing it alone.</h2>
            <p className="lp-coach-lede">
              An agent checks your proof every day, remembers your streak, and nudges you through
              the days you'd rather skip — then settles the verdict when the deadline hits.
            </p>
          </div>
          <div className="lp-coach-card" data-reveal style={{ transitionDelay: ".1s" }}>
            <div className="lp-coach-top">
              <span className="lp-coach-avatar">✦</span>
              <div>
                <div className="lp-coach-name">Hermes</div>
                <div className="lp-coach-status">Coaching your workout pact</div>
              </div>
            </div>
            <div className="lp-coach-bubble">Three down, two to go. You're ahead of last week — keep the rhythm.</div>
            <div className="lp-coach-chip">✓ Proof verified — Thursday workout</div>
            <div className="lp-coach-bubble">One session left and the week is clean. Don't hand $40 to charity tonight.</div>
          </div>
        </div>
      </section>

      {/* ── The deck (placeholder for the future create step-1) ───────────────── */}
      <section className="lp-section lp-deck-sec">
        <div className="lp-wrap">
          <div className="lp-deck-head" data-reveal>
            <div>
              <div className="lp-eyebrow m">It starts with one card</div>
              <h2 className="lp-sec-title">Pick what you're committing to.</h2>
              <p className="lp-coach-lede">
                Browse the deck, choose a goal, and shape it into a real pact — frequency, stake,
                and the cause that gets paid if you fold.
              </p>
              <button className="lp-deck-cta" onClick={onboard}>
                Browse the deck <span>→</span>
              </button>
            </div>
          </div>
          <div className="lp-deck-fan" data-reveal style={{ transitionDelay: ".1s" }}>
            {DECK.map((c, i) => (
              <button
                key={c.title}
                className="lp-deck-card"
                onClick={onboard}
                style={{ transform: `rotate(${c.rot}deg) translateY(${i === 1 ? -10 : 14}px)` }}
              >
                <div className="lp-deck-ico">{c.icon}</div>
                <div className="lp-deck-card-title">{c.title}</div>
                <div className="lp-deck-card-sub">{c.sub}</div>
                <div className="lp-deck-card-foot m">
                  <span>pact</span>
                  <span>{c.no}</span>
                </div>
              </button>
            ))}
          </div>
          <div className="lp-placeholder m" data-reveal>
            ⌁ first step of the create flow lands here
          </div>
        </div>
      </section>

      {/* ── Final CTA + footer ──────────────────────────────────────────────── */}
      <section className="lp-section lp-final">
        <div className="lp-final-spark">✦</div>
        <h2 className="lp-final-title">Become the better version of yourself.</h2>
        <p className="lp-final-sub">
          One promise. Real stakes. An agent in your corner. It starts the moment you stop wishing.
        </p>
        <button className="lp-final-cta" onClick={onboard}>
          Make your first pact <span>→</span>
        </button>
        <div className="lp-footer m">Put it on the line · ✦ · 2026</div>
      </section>
    </div>
  );
}

const DECK = [
  { title: "Work out", sub: "Move your body", no: "01", rot: -6, icon: <Dumbbell /> },
  { title: "Read", sub: "Feed your mind", no: "02", rot: 0, icon: <Book /> },
  { title: "Custom", sub: "Make your own", no: "+", rot: 6, icon: <Plus /> },
];

const ICON = {
  target: <Clock />,
  coin: <Coin />,
  camera: <Camera />,
  spark: <Spark />,
};

function Clock() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="23" height="23">
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4l3 2" />
    </svg>
  );
}
function Coin() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="23" height="23">
      <path d="M12 3v18M7 8h7a3 3 0 0 1 0 6H6" />
    </svg>
  );
}
function Camera() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="23" height="23">
      <path d="M4 8h3l1.5-2h7L17 8h3v11H4Z" />
      <circle cx="12" cy="13" r="3.4" />
    </svg>
  );
}
function Spark() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="23" height="23">
      <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8Z" />
    </svg>
  );
}
function Dumbbell() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="22" height="22">
      <path d="M3 9v6M6 7.5v9M18 7.5v9M21 9v6M6 12h12" />
    </svg>
  );
}
function Book() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width="22" height="22">
      <path d="M5 4a1 1 0 0 1 1-1h12v16H6a1 1 0 0 0-1 1Z" />
      <path d="M18 3v16" />
    </svg>
  );
}
function Plus() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="22" height="22">
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

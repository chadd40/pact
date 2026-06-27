import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, DEMO_OWNER } from "../api";
import { useDemo } from "../App";
import type { Charity, Pact } from "../types";
import "./create.css";

// ── Goal deck ─────────────────────────────────────────────────────────────────
// Five named templates each carry the painterly front art (with its title baked
// in) + a template key. The sixth card is "Create your own": a dashed front that
// reveals a free-text title input and sends a null template.
interface GoalCard {
  title: string;
  desc: string;
  template: string | null;
  art: string | null; // public path to the front-card SVG; null = custom
}

const GOALS: GoalCard[] = [
  { title: "Work out", desc: "Move your body", template: "workout", art: "/cards/workout.svg" },
  { title: "Read", desc: "Feed your mind", template: "read", art: "/cards/read.svg" },
  { title: "Ship something", desc: "Build in public", template: "ship_daily", art: "/cards/ship.svg" },
  { title: "Meditate", desc: "Find some quiet", template: "meditate", art: "/cards/meditate.svg" },
  { title: "No phone at night", desc: "Reclaim your evenings", template: "no_phone_night", art: "/cards/nophone.svg" },
  { title: "Custom goal", desc: "Make your own", template: null, art: null },
];
const CUSTOM_INDEX = GOALS.length - 1;

// Shown as the signature line on the card back. Until accounts exist, the signer's
// real name isn't known at creation time — show a placeholder. Swap to the
// registered user's name here once that's available.
const OWNER_NAME = "Your Name";

// Agents the card can be "kept honest by".
interface AgentDef {
  key: string;
  name: string; // as written on the card back
  blurb: string;
  avatar: string | null; // image, else a glyph tile
  tag: "rec" | "connect";
  glyph?: JSX.Element;
}
const AGENTS: AgentDef[] = [
  { key: "Hermes", name: "Hermes Agent", blurb: "Your built-in coach", avatar: "/agents/hermes.png", tag: "rec" },
  {
    key: "Claude Code",
    name: "Claude Code",
    blurb: "From your dev workflow",
    avatar: null,
    tag: "connect",
    glyph: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="20" height="20">
        <path d="M8 7l-5 5 5 5M16 7l5 5-5 5" />
      </svg>
    ),
  },
  {
    key: "your agent",
    name: "Your own agent",
    blurb: "Any MCP agent, via API",
    avatar: null,
    tag: "connect",
    glyph: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="20" height="20">
        <rect x="4" y="4" width="16" height="16" rx="4" />
        <path d="M9 12h6M12 9v6" />
      </svg>
    ),
  },
];

// Stages: 0 deck · 1 frequency · 2 stake · 3 charity · 4 agent · 5 sealing · 6 message
type Stage = 0 | 1 | 2 | 3 | 4 | 5 | 6;

const WEEK_OPTIONS = [1, 4, 8, 12];
const STAKE_PRESETS = [50, 100, 200, 500];
const STAKE_MIN = 10;
const STAKE_MAX = 500;

// Fixed prototype world; scaled to fit the viewport.
const STAGE_W = 1080;
const STAGE_H = 760;
const DECK_SCALE = 0.72;

const Arrow = ({ size = 16 }: { size?: number }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" width={size} height={size}>
    <path d="M5 12h13M12 6l6 6-6 6" />
  </svg>
);
const Chevron = ({ dir, size = 20 }: { dir: "l" | "r"; size?: number }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" width={size} height={size}>
    {dir === "l" ? <path d="M15 6l-6 6 6 6" /> : <path d="M9 6l6 6-6 6" />}
  </svg>
);
const Spark = ({ size = 24 }: { size?: number }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width={size} height={size}>
    <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8Z" />
  </svg>
);

export function Create() {
  const navigate = useNavigate();
  const { signalChange } = useDemo();

  const [stage, setStage] = useState<Stage>(0);
  const [active, setActive] = useState(0); // carousel focus index
  const [goalIndex, setGoalIndex] = useState<number | null>(null); // chosen card
  const [customTitle, setCustomTitle] = useState("");
  const [days, setDays] = useState(5);
  const [weeks, setWeeks] = useState(4);
  const [stake, setStake] = useState(200);
  const [charityId, setCharityId] = useState<string | null>(null);
  const [agentKey, setAgentKey] = useState<string | null>(null);
  // Reveal beat: after the flip lands, the card "loads" — title + frequency
  // resolve out of the skeleton and the editor rail comes alive.
  const [editorReady, setEditorReady] = useState(false);

  const [charities, setCharities] = useState<Charity[]>([]);
  const [created, setCreated] = useState<Pact | null>(null);
  const [error, setError] = useState<string | null>(null);

  const stageRef = useRef(stage);
  stageRef.current = stage;

  // Fetch the real charity catalog once.
  useEffect(() => {
    let alive = true;
    api
      .charities()
      .then((cs) => alive && setCharities(cs))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  // Responsive scale: fit the fixed world into the *visible* area below the
  // sticky demo bar, so the stage centers correctly and nothing clips under the fold.
  const rootRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const apply = () => {
      const top = el.getBoundingClientRect().top;
      const avail = window.innerHeight - top;
      el.style.minHeight = `${avail}px`;
      const pad = 28;
      const w = el.clientWidth - pad;
      const h = avail - pad;
      const scale = Math.min(w / STAGE_W, h / STAGE_H, 1);
      el.style.setProperty("--pc-scale", String(Math.max(scale, 0.3)));
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(el);
    window.addEventListener("resize", apply);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", apply);
    };
  }, []);

  // Move keyboard focus onto the active surface when the stage changes, so focus
  // is never stranded on hidden deck controls.
  const railHeadRef = useRef<HTMLHeadingElement>(null);
  const openBtnRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (stage === 1 && isCustom) return; // the name input auto-focuses itself
    if (stage >= 1 && stage <= 4) railHeadRef.current?.focus();
    else if (stage === 6) openBtnRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage]);

  const selectedGoal = goalIndex ?? active;
  const isCustom = selectedGoal === CUSTOM_INDEX;
  const goalCard = GOALS[selectedGoal];
  const goalName = isCustom ? customTitle.trim() || "Your goal" : goalCard.title;

  const charity = charities.find((c) => c.id === charityId) || null;
  const agentDef = AGENTS.find((a) => a.key === agentKey) || null;

  const checkins = days * weeks;
  const weeksWord = weeks === 1 ? "week" : "weeks";

  const sealedDate = new Date()
    .toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
    .toUpperCase();

  // ── Transitions ───────────────────────────────────────────────────────────
  const select = (i: number) => {
    // Fresh card every time — don't carry over a prior in-progress pact.
    setDays(5);
    setWeeks(4);
    setStake(200);
    setCharityId(null);
    setAgentKey(null);
    if (i !== CUSTOM_INDEX) setCustomTitle("");
    setGoalIndex(i);
    setActive(i);
    setStage(1);
    setEditorReady(false);
    // Let the flip land (.85s + .1s delay), then "load" the first section.
    window.setTimeout(() => {
      if (stageRef.current === 1) setEditorReady(true);
    }, 980);
  };

  const tap = (i: number) => {
    if (stage !== 0) return;
    if (i !== active) setActive(i);
    else select(i);
  };

  const prev = () => setActive((a) => Math.max(0, a - 1));
  const next = () => setActive((a) => Math.min(GOALS.length - 1, a + 1));

  const back = () => {
    setError(null);
    if (stage === 1) {
      // Flip back to the deck.
      setStage(0);
      setEditorReady(false);
      window.setTimeout(() => {
        if (stageRef.current === 0) setGoalIndex(null);
      }, 520);
      return;
    }
    setStage((s) => Math.max(1, (s - 1) as Stage) as Stage);
  };

  const advance = () => {
    if (stage === 1 && isCustom && !customTitle.trim()) return;
    if (stage === 3 && !charityId) return;
    setStage((s) => Math.min(4, (s + 1) as Stage) as Stage);
  };

  const seal = async () => {
    if (!charityId || !agentKey) return;
    if (stageRef.current >= 5) return; // guard against double-seal (duplicate pacts)
    setError(null);
    setStage(5);
    try {
      const pact = await api.createPact({
        goal_title: goalName,
        goal_template: goalCard.template,
        days_per_week: days,
        weeks,
        stake_amount_cents: stake * 100,
        charity_id: charityId,
        agent: agentKey,
        consent_acknowledged: true,
        owner: DEMO_OWNER,
      });
      setCreated(pact);
      signalChange();
      window.setTimeout(() => setStage(6), 1300);
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail : "Could not seal the pact. Try again.";
      setError(detail);
      setStage(4);
    }
  };

  const openPact = () => {
    if (created) navigate(`/pact/${created.id}`);
  };

  const restart = () => {
    setStage(0);
    setActive(0);
    setGoalIndex(null);
    setCustomTitle("");
    setDays(5);
    setWeeks(4);
    setStake(200);
    setCharityId(null);
    setAgentKey(null);
    setEditorReady(false);
    setCreated(null);
    setError(null);
  };

  // ── Card slot / flip transforms ─────────────────────────────────────────────
  const slotTransform = (a: number, b: number, c: number, ry: number, s: number) =>
    `translate(-50%,-50%) translateX(${a}px) translateY(${b}px) translateZ(${c}px) rotateY(${ry}deg) scale(${s})`;

  const slotStyle = (i: number): React.CSSProperties => {
    if (stage === 0) {
      const off = i - active;
      const a = Math.abs(off);
      const s = DECK_SCALE * Math.max(0.74, 1 - a * 0.12);
      return {
        transform: slotTransform(off * 250, 0, -a * 150, off * -32, s),
        opacity: a > 2 ? 0 : 1,
        zIndex: 100 - a,
        transition: "transform .6s cubic-bezier(.32,.62,.3,1), opacity .5s ease",
      };
    }
    // hero (chosen card)
    if (i === goalIndex) {
      const exiting = stage >= 5;
      return {
        transform: slotTransform(-258, exiting ? 44 : 0, 60, 0, exiting ? 0.86 : 1),
        opacity: stage === 6 ? 0 : 1,
        zIndex: 200,
        transition: "transform .72s cubic-bezier(.34,.72,.26,1), opacity .55s ease",
      };
    }
    // fly away
    const off = i - (goalIndex ?? 0);
    const dir = off >= 0 ? 1 : -1;
    const a = Math.abs(off);
    return {
      transform: slotTransform(dir * (700 + a * 46), 0, -300, dir * -50, 0.64),
      opacity: 0,
      zIndex: 20,
      pointerEvents: "none",
      transition: "transform .62s cubic-bezier(.4,.5,.3,1), opacity .55s ease",
    };
  };

  const flipStyle = (i: number): React.CSSProperties => {
    const flipped = stage >= 1 && i === goalIndex;
    return {
      transform: `rotateY(${flipped ? 180 : 0}deg)`,
      transition: "transform .85s cubic-bezier(.2,.72,.26,1) .1s",
    };
  };

  // ── Card-back section resolution (skeleton → live → locked) ──────────────────
  const titleReady = stage >= 1 && (editorReady || stage > 1);
  const freqReady = stage > 1 || (stage === 1 && editorReady);
  const stakeReady = stage >= 2;
  const charityReady = stage >= 3 && !!charity;
  const agentReady = stage >= 4 && !!agentDef;
  const signed = stage >= 5;
  const zoneState = (n: number) => (stage === n ? "active" : stage > n ? "done" : "pending");

  const deckMode = stage === 0;
  const editing = stage >= 1 && stage <= 4;

  // ── Editor rail step copy ────────────────────────────────────────────────────
  const stepMeta =
    stage === 1
      ? { n: 1, head: isCustom ? "Name it & set the pace" : "Set the pace" }
      : stage === 2
      ? { n: 2, head: "Put it on the line" }
      : stage === 3
      ? { n: 3, head: "Choose the cause" }
      : stage === 4
      ? { n: 4, head: "Pick your keeper" }
      : { n: 0, head: "" };

  const canContinue =
    stage === 1 ? !isCustom || !!customTitle.trim() : stage === 3 ? !!charityId : true;

  return (
    <div className="pc-root" ref={rootRef}>
      <div className="pc-stage">
        <div className="pc-vignette" />

        {/* Brand wordmark */}
        <div className="pc-brand">pact</div>

        {/* Back */}
        <button
          type="button"
          className="pc-back"
          onClick={back}
          disabled={!editing}
          aria-hidden={!editing}
          style={{
            opacity: editing ? 1 : 0,
            pointerEvents: editing ? "auto" : "none",
          }}
        >
          <Chevron dir="l" size={15} />
          Back
        </button>

        {/* Carousel heading */}
        <div className="pc-heading" style={{ opacity: deckMode ? 1 : 0 }}>
          <div className="m eyebrow">New pact · Step 1</div>
          <h1>What are you committing to?</h1>
          <div className="sub">Browse the deck. Click a card to choose it.</div>
        </div>

        {/* 3D world of flip cards */}
        <div className="pc-world">
          <div className="pc-world-inner">
            {GOALS.map((g, i) => {
              const isHero = i === goalIndex;
              return (
                <div
                  key={g.title}
                  className="pc-slot"
                  style={slotStyle(i)}
                  onClick={() => tap(i)}
                  onKeyDown={(e) => {
                    if (deckMode && (e.key === "Enter" || e.key === " ")) {
                      e.preventDefault();
                      tap(i);
                    }
                  }}
                  role={deckMode ? "button" : undefined}
                  tabIndex={deckMode ? 0 : -1}
                  aria-hidden={!deckMode && !isHero}
                  aria-label={deckMode ? `${g.title} — ${g.desc}` : undefined}
                >
                  <div className="pc-flip" style={flipStyle(i)}>
                    {/* FRONT */}
                    <div className="pc-face pc-front">
                      {g.art ? (
                        <img className="pc-art" src={g.art} alt="" draggable={false} />
                      ) : (
                        <div className="pc-custom-front">
                          <div className="cf-plus">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" width="30" height="30">
                              <path d="M12 5v14M5 12h14" />
                            </svg>
                          </div>
                          <div className="cf-text">
                            <div className="cf-title">Create your own</div>
                            <div className="cf-sub">Start from a blank card</div>
                          </div>
                          <div className="cf-foot m">
                            <span>pact</span>
                            <span>+</span>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* BACK — only the chosen card needs the editorial face */}
                    <div className="pc-face pc-back-face">
                      {isHero && (
                        <CardBack
                          goalName={goalName}
                          days={days}
                          weeks={weeks}
                          weeksWord={weeksWord}
                          stake={stake}
                          charity={charity}
                          agent={agentDef}
                          owner={OWNER_NAME}
                          sealedDate={sealedDate}
                          titleReady={titleReady}
                          freqReady={freqReady}
                          stakeReady={stakeReady}
                          charityReady={charityReady}
                          agentReady={agentReady}
                          signed={signed}
                          zoneState={zoneState}
                        />
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Carousel arrows */}
        <button
          className="pc-arrow prev"
          onClick={prev}
          disabled={active === 0}
          tabIndex={deckMode ? 0 : -1}
          aria-hidden={!deckMode}
          style={{ opacity: deckMode ? 1 : 0, pointerEvents: deckMode ? "auto" : "none" }}
          aria-label="Previous card"
        >
          <Chevron dir="l" />
        </button>
        <button
          className="pc-arrow next"
          onClick={next}
          disabled={active === GOALS.length - 1}
          tabIndex={deckMode ? 0 : -1}
          aria-hidden={!deckMode}
          style={{ opacity: deckMode ? 1 : 0, pointerEvents: deckMode ? "auto" : "none" }}
          aria-label="Next card"
        >
          <Chevron dir="r" />
        </button>

        {/* Choose pill */}
        <button
          className="pc-choose"
          onClick={() => select(active)}
          tabIndex={deckMode ? 0 : -1}
          aria-hidden={!deckMode}
          style={{ opacity: deckMode ? 1 : 0, pointerEvents: deckMode ? "auto" : "none" }}
        >
          Choose this card <Arrow size={17} />
        </button>

        {/* ── Editor rail (stages 1–4) ─────────────────────────────────────────── */}
        <div
          className="pc-rail"
          style={{
            opacity: editing ? 1 : 0,
            transform: editing ? "translate(0,-50%)" : "translate(24px,-50%)",
            pointerEvents: editing ? "auto" : "none",
          }}
        >
          <div className="pc-rail-head">
            <div className="m step">Step {stepMeta.n} of 4</div>
            <h2 ref={railHeadRef} tabIndex={-1}>{stepMeta.head}</h2>
          </div>

          <div className="pc-rail-body">
            {/* FREQUENCY */}
            {stage === 1 && (
              <div className="pc-panel">
                {isCustom && (
                  <input
                    className="pc-name-input"
                    placeholder="Name your goal…"
                    aria-label="Name your goal"
                    value={customTitle}
                    autoFocus
                    maxLength={60}
                    onChange={(e) => setCustomTitle(e.target.value)}
                  />
                )}
                <div className="pc-freq-top">
                  <div
                    className="pc-freq-num"
                    role="spinbutton"
                    aria-label="Days per week"
                    aria-valuenow={days}
                    aria-valuemin={1}
                    aria-valuemax={7}
                  >
                    <span className="n m">{days}</span>
                    <span className="u">days<br />a week</span>
                  </div>
                  <div className="pc-step-btns">
                    <button className="pc-step-btn" onClick={() => setDays((d) => Math.max(1, d - 1))} aria-label="Fewer days per week">−</button>
                    <button className="pc-step-btn" onClick={() => setDays((d) => Math.min(7, d + 1))} aria-label="More days per week">+</button>
                  </div>
                </div>
                <div className="pc-bars" aria-hidden="true">
                  {[1, 2, 3, 4, 5, 6, 7].map((n) => (
                    <div key={n} className={`pc-bar ${days >= n ? "on" : ""}`} />
                  ))}
                </div>
                <div className="pc-sub-label m">Commit for</div>
                <div className="pc-week-pills">
                  {WEEK_OPTIONS.map((w) => (
                    <button
                      key={w}
                      className={`pc-pill ${weeks === w ? "sel" : ""}`}
                      onClick={() => setWeeks(w)}
                      aria-pressed={weeks === w}
                    >
                      {w} {w === 1 ? "wk" : "wks"}
                    </button>
                  ))}
                </div>
                <div className="pc-checkins m">= {checkins} check-ins over the pact</div>
              </div>
            )}

            {/* STAKE */}
            {stage === 2 && (
              <div className="pc-panel">
                <div className="pc-stake-amt m">${stake}</div>
                <div className="pc-slider">
                  <input
                    type="range"
                    min={STAKE_MIN}
                    max={STAKE_MAX}
                    step={10}
                    value={stake}
                    onChange={(e) => setStake(Number(e.target.value))}
                  />
                </div>
                <div className="pc-preset-pills">
                  {STAKE_PRESETS.map((v) => (
                    <button
                      key={v}
                      className={`pc-pill ${stake === v ? "sel" : ""}`}
                      onClick={() => setStake(v)}
                      aria-pressed={stake === v}
                    >
                      ${v}
                    </button>
                  ))}
                </div>
                <div className="pc-help m">If you miss a check-in, this is what you forfeit to your cause.</div>
              </div>
            )}

            {/* CHARITY */}
            {stage === 3 && (
              <div className="pc-panel">
                <div className="pc-chips pc-chips-stamps">
                  {charities.map((c) => {
                    const sel = charityId === c.id;
                    return (
                      <button
                        key={c.id}
                        type="button"
                        className={`pc-chip-stamp${sel ? " sel" : ""}`}
                        title={c.name}
                        onClick={() => setCharityId(c.id)}
                        aria-pressed={sel}
                      >
                        <img src={c.stamp} alt={c.name} loading="lazy" />
                      </button>
                    );
                  })}
                </div>
                <div className="pc-charity-label">
                  {charity ? `${charity.name} · ${charity.category.replace(/_/g, " ")}` : "Tap a cause to stamp it on"}
                </div>
              </div>
            )}

            {/* AGENT */}
            {stage === 4 && (
              <div className="pc-panel">
                <div className="pc-agent-list">
                  {AGENTS.map((a) => {
                    const sel = agentKey === a.key;
                    return (
                      <button
                        key={a.key}
                        type="button"
                        className={`pc-agent-opt${sel ? " sel" : ""}`}
                        onClick={() => setAgentKey(a.key)}
                        aria-pressed={sel}
                      >
                        <span className="ao-ic">
                          {a.avatar ? <img src={a.avatar} alt="" /> : a.glyph}
                        </span>
                        <span className="ao-text">
                          <span className="ao-name">{a.name}</span>
                          <span className="ao-blurb">{a.blurb}</span>
                        </span>
                        <span className={`ao-tag m ${a.tag}`}>{a.tag === "rec" ? "Recommended" : "Connect"}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          <div className="pc-rail-foot">
            {stage < 4 ? (
              <button className="pc-continue" onClick={advance} disabled={!canContinue}>
                Continue <Arrow />
              </button>
            ) : (
              <button className="pc-continue seal" onClick={seal} disabled={!agentKey}>
                Seal the pact <Arrow />
              </button>
            )}
          </div>
        </div>

        {/* Sealing (stage 5) */}
        <div className="pc-sending" style={{ opacity: stage === 5 ? 1 : 0 }}>
          <div className="pill">
            <span className="txt m">Sealing your pact with {agentDef?.name || "your agent"}</span>
            <span className="pc-dots"><span /><span /><span /></span>
          </div>
        </div>

        {/* Message (stage 6) */}
        <div
          className="pc-msg"
          style={{ opacity: stage === 6 ? 1 : 0, pointerEvents: stage === 6 ? "auto" : "none" }}
        >
          <div className="card" style={{ transform: stage === 6 ? "translateY(0)" : "translateY(14px)" }}>
            <div className="head">
              <div className="ic">
                {agentDef?.avatar ? <img src={agentDef.avatar} alt="" /> : <Spark size={22} />}
              </div>
              <div>
                <div className="nm">{agentDef?.name || "Hermes Agent"}</div>
                <div className="status"><span className="dot" />Now coaching your pact</div>
              </div>
            </div>
            <div className="body">
              <div className="bubble">
                Let's go — we've got a pact. <b>${stake}</b> is on the line behind{" "}
                <b>{goalName.toLowerCase()}</b>, {days} days/week for {weeks} {weeksWord}. I'll get you
                started: your <b>first check-in is tomorrow</b>. Miss it and{" "}
                {charity?.name || "your charity"} gets paid — so let's not.
              </div>
              <div className="actions">
                <button className="open" ref={openBtnRef} onClick={openPact}>
                  Open my pact <Arrow />
                </button>
                <button className="replay" onClick={restart}>Replay</button>
              </div>
            </div>
          </div>
        </div>

        {/* Error toast */}
        {error && (
          <div className="pc-error" role="alert">
            <span>{error}</span>
            <button type="button" className="x" onClick={() => setError(null)} aria-label="Dismiss error">✕</button>
          </div>
        )}
      </div>

      {/* Small-screen fallback — sibling of the stage so it survives the stage being hidden */}
      <div className="pc-mobile-note">
        <div className="mn-mark">pact</div>
        <h2>Make your pact on a bigger screen</h2>
        <p>The card deck is designed for desktop. Open Pact on a laptop to choose a card and seal your commitment.</p>
      </div>
    </div>
  );
}

// ── The editorial card back ────────────────────────────────────────────────────
// Mirrors the workout_card_back.svg layout: commitment → on the line → cause →
// keeper → signature. Each section fades from a shimmer skeleton into its value
// as the user fills the pact out.
interface CardBackProps {
  goalName: string;
  days: number;
  weeks: number;
  weeksWord: string;
  stake: number;
  charity: Charity | null;
  agent: AgentDef | null;
  owner: string;
  sealedDate: string;
  titleReady: boolean;
  freqReady: boolean;
  stakeReady: boolean;
  charityReady: boolean;
  agentReady: boolean;
  signed: boolean;
  zoneState: (n: number) => string;
}

function CardBack(p: CardBackProps) {
  return (
    <div className="cb">
      <div className="cb-top">
        <div className="cb-eyebrow m">The commitment</div>
        {p.titleReady ? (
          <div className="cb-title">{p.goalName}</div>
        ) : (
          <div className="pc-sk cb-sk-title" />
        )}
        {p.freqReady ? (
          <div className={`cb-freq ${p.zoneState(1)}`}>
            {p.days} days a week for {p.weeks} {p.weeksWord}
          </div>
        ) : (
          <div className="pc-sk cb-sk-freq" />
        )}
      </div>

      <div className="cb-rule" />

      <div className="cb-section">
        <div className="cb-eyebrow m">On the line</div>
        {p.stakeReady ? (
          <div className={`cb-stake m ${p.zoneState(2)}`}>${p.stake}</div>
        ) : (
          <div className="pc-sk cb-sk-stake" />
        )}
      </div>

      <div className="cb-section">
        <div className="cb-eyebrow m">If you fail, it funds</div>
        {p.charityReady && p.charity ? (
          <div className={`cb-row ${p.zoneState(3)}`}>
            <img className="cb-seal" src={p.charity.stamp} alt="" />
            <span className="cb-row-name m">{p.charity.name}</span>
          </div>
        ) : (
          <div className="cb-row">
            <div className="pc-sk cb-sk-seal" />
            <div className="pc-sk cb-sk-name" />
          </div>
        )}
      </div>

      <div className="cb-section">
        <div className="cb-eyebrow m">Kept honest by</div>
        {p.agentReady && p.agent ? (
          <div className={`cb-row ${p.zoneState(4)}`}>
            <span className="cb-avatar">
              {p.agent.avatar ? <img src={p.agent.avatar} alt="" /> : p.agent.glyph}
            </span>
            <span className="cb-row-name m">{p.agent.name}</span>
          </div>
        ) : (
          <div className="cb-row">
            <div className="pc-sk cb-sk-avatar" />
            <div className="pc-sk cb-sk-name" />
          </div>
        )}
      </div>

      <div className="cb-foot">
        <div className="cb-rule" />
        <div className={`cb-sign ${p.signed ? "in" : ""}`}>
          <div className="cb-sign-name">{p.owner}</div>
          <div className="cb-sign-date m">{p.signed ? `SIGNED · ${p.sealedDate}` : "AWAITING SIGNATURE"}</div>
        </div>
      </div>
    </div>
  );
}

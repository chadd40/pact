import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, DEMO_OWNER } from "../api";
import { useDemo } from "../App";
import type { Charity, Pact } from "../types";
import "./create.css";

// ── Goal deck ─────────────────────────────────────────────────────────────────
// The 5 named templates carry a title + a template key; "Custom goal" reveals a
// free-text title input and sends a null template.
interface GoalCard {
  title: string;
  desc: string;
  template: string | null;
  icon: JSX.Element;
}

const ICON = {
  workout: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="28" height="28">
      <path d="M3 9v6M6 7.5v9M18 7.5v9M21 9v6M6 12h12" />
    </svg>
  ),
  read: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width="27" height="27">
      <path d="M5 4a1 1 0 0 1 1-1h12v16H6a1 1 0 0 0-1 1Z" />
      <path d="M18 3v16" />
    </svg>
  ),
  ship: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="27" height="27">
      <path d="M13 3 5 13h6l-1 8 8-10h-6l1-8Z" />
    </svg>
  ),
  meditate: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width="27" height="27">
      <path d="M5 19c8 1 14-5 14-14 0 0-13-1-13 8a6 6 0 0 0 2 6Z" />
    </svg>
  ),
  phone: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width="27" height="27">
      <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z" />
    </svg>
  ),
  custom: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="27" height="27">
      <path d="M12 5v14M5 12h14" />
    </svg>
  ),
};

const GOALS: GoalCard[] = [
  { title: "Work out", desc: "Move your body", template: "workout", icon: ICON.workout },
  { title: "Read", desc: "Feed your mind", template: "read", icon: ICON.read },
  { title: "Ship daily", desc: "Build in public", template: "ship_daily", icon: ICON.ship },
  { title: "Meditate", desc: "Find some quiet", template: "meditate", icon: ICON.meditate },
  { title: "No phone at night", desc: "Reclaim your evenings", template: "no_phone_night", icon: ICON.phone },
  { title: "Custom goal", desc: "Make your own", template: null, icon: ICON.custom },
];
const CUSTOM_INDEX = GOALS.length - 1;

// Stages: 0 deck · 1 frequency · 2 stake · 3 charity · 4 agent · 5 sending · 6 message
type Stage = 0 | 1 | 2 | 3 | 4 | 5 | 6;

const WEEK_OPTIONS = [1, 4, 8, 12];
const STAKE_PRESETS = [50, 100, 200, 500];
const STAKE_MIN = 10;
const STAKE_MAX = 500;

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
  const [goalIndex, setGoalIndex] = useState<number | null>(null);
  const [customTitle, setCustomTitle] = useState("");
  const [days, setDays] = useState(5);
  const [weeks, setWeeks] = useState(4);
  const [stake, setStake] = useState(200);
  const [charityId, setCharityId] = useState<string | null>(null);
  const [agent, setAgent] = useState<string | null>(null);
  const [freqUp, setFreqUp] = useState(false); // shimmer → active reveal
  const [zonesShown, setZonesShown] = useState(true);

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

  // Responsive scale: fit the fixed 1080×760 world into the viewport.
  const rootRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const STAGE_W = 1080;
    const STAGE_H = 760;
    const apply = () => {
      const pad = 32;
      const w = el.clientWidth - pad;
      const h = el.clientHeight - pad;
      const scale = Math.min(w / STAGE_W, h / STAGE_H, 1);
      el.style.setProperty("--pc-scale", String(Math.max(scale, 0.3)));
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Re-trigger the zones fade when the carousel focus changes on the deck.
  useEffect(() => {
    if (stage !== 0) return;
    setZonesShown(false);
    const id = requestAnimationFrame(() =>
      requestAnimationFrame(() => setZonesShown(true))
    );
    return () => cancelAnimationFrame(id);
  }, [active, stage]);

  const selectedGoal = goalIndex ?? active;
  const isCustom = selectedGoal === CUSTOM_INDEX;
  const goalCard = GOALS[selectedGoal];
  const goalName = isCustom ? customTitle.trim() || "Custom goal" : goalCard.title;

  const charity = charities.find((c) => c.id === charityId) || null;

  const checkins = days * weeks;
  const weeksWord = weeks === 1 ? "week" : "weeks";

  // ── Transitions ───────────────────────────────────────────────────────────
  const select = (i: number) => {
    setGoalIndex(i);
    setStage(1);
    setFreqUp(false);
    window.setTimeout(() => {
      if (stageRef.current === 1) setFreqUp(true);
    }, 820);
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
    setStage((s) => Math.max(0, (s - 1) as Stage) as Stage);
  };

  const advance = () => {
    if (stage === 3 && !charityId) return; // Seal it disabled until a charity is picked
    setStage((s) => Math.min(4, (s + 1) as Stage) as Stage);
  };

  const pickAgent = async (name: string) => {
    if (!charityId) return;
    setAgent(name);
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
        agent: name,
        consent_acknowledged: true,
        owner: DEMO_OWNER,
      });
      setCreated(pact);
      signalChange();
      // Brief "handing to agent" beat before the message bubble.
      window.setTimeout(() => setStage(6), 1100);
    } catch (e) {
      const detail =
        e instanceof ApiError ? e.detail : "Could not seal the pact. Try again.";
      setError(detail);
      setStage(4); // back to the agent panel so they can retry
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
    setAgent(null);
    setCreated(null);
    setError(null);
  };

  // ── Carousel / detail transforms (ported from prototype emb()/detailStyle) ──
  const embStyle = (i: number): React.CSSProperties => {
    const base = "translate(-50%,-50%)";
    if (stage === 0) {
      const off = i - active;
      const a = Math.abs(off);
      const tx = off * 232;
      const tz = -a * 148;
      const ry = off * -33;
      const sc = Math.max(0.66, 1 - a * 0.12);
      return {
        transform: `${base} translateX(${tx}px) translateZ(${tz}px) rotateY(${ry}deg) scale(${sc})`,
        opacity: a > 2 ? 0 : 1,
        zIndex: 100 - a,
        transition: "transform .55s cubic-bezier(.32,.62,.3,1),opacity 0s",
      };
    }
    const gi = goalIndex ?? active;
    if (i === gi) {
      return {
        transform: `${base} scale(.94)`,
        opacity: 0,
        zIndex: 40,
        pointerEvents: "none",
        transition: "opacity 0s",
      };
    }
    const off = i - gi;
    const t = off + (off > 0 ? 1 : -1);
    const a = Math.abs(t);
    const tx = t * 232;
    const tz = -a * 148;
    const ry = t * -33;
    const sc = Math.max(0.6, 1 - a * 0.12);
    return {
      transform: `${base} translateX(${tx}px) translateZ(${tz}px) rotateY(${ry}deg) scale(${sc})`,
      opacity: 0,
      zIndex: 20 - a,
      pointerEvents: "none",
      transition: "transform .5s cubic-bezier(.32,.62,.3,1),opacity 0s",
    };
  };

  const detailStyle = (): React.CSSProperties => {
    const base = "translate(-50%,-50%)";
    if (stage === 0)
      return {
        transform: `${base} scale(.74)`,
        opacity: 0,
        pointerEvents: "none",
        transition: "transform .55s cubic-bezier(.32,.62,.3,1),opacity .42s ease",
      };
    if (stage <= 3)
      return {
        transform: `${base} scale(1)`,
        opacity: 1,
        pointerEvents: "auto",
        transition: "transform .6s cubic-bezier(.3,.68,.32,1),opacity .5s ease",
      };
    if (stage === 4)
      return {
        transform: `${base} translateY(-128px) scale(.76)`,
        opacity: 1,
        pointerEvents: "auto",
      };
    return {
      transform: `${base} translateY(-150px) scale(.42)`,
      opacity: 0,
      pointerEvents: "none",
    };
  };

  // Zone visual state (active glow / reached opacity), per prototype zone(n).
  const zoneClass = (n: number) =>
    `pc-zone ${stage === n ? "active" : ""} ${stage >= n ? "" : "dim"}`;

  const chooseVisible = stage === 0;
  const barVisible = stage >= 1 && stage <= 3;
  const stepName =
    stage === 1 ? "Frequency" : stage === 2 ? "On the line" : stage === 3 ? "The stamp" : "";

  const agentName = agent || "Hermes";
  const freqSummary = `${days} days/week · ${weeks} ${weeksWord}`;

  return (
    <div className="pc-root" ref={rootRef}>
      <div className="pc-stage">
        <div className="pc-vignette" />

        {/* Brand wordmark (Caveat) */}
        <div className="pc-brand">pact</div>

        {/* Back */}
        <div
          className="pc-back"
          onClick={back}
          style={{
            opacity: stage >= 1 && stage <= 4 ? 1 : 0,
            pointerEvents: stage >= 1 && stage <= 4 ? "auto" : "none",
          }}
        >
          <Chevron dir="l" size={15} />
          Back
        </div>

        {/* Carousel heading */}
        <div className="pc-heading" style={{ opacity: stage === 0 ? 1 : 0 }}>
          <div className="m eyebrow">New pact · Step 1</div>
          <h1>What are you committing to?</h1>
          <div className="sub">Browse the deck. Click a card to choose it.</div>
        </div>

        {/* 3D world */}
        <div className="pc-world">
          <div className="pc-world-inner">
            {GOALS.map((g, i) => (
              <div
                key={g.title}
                className={`pc-emblem ${i === CUSTOM_INDEX ? "custom" : ""}`}
                style={embStyle(i)}
                onClick={() => tap(i)}
              >
                {i !== CUSTOM_INDEX && <div className="glow" />}
                <div className="body">
                  <div className="ic">{g.icon}</div>
                  <div style={{ marginTop: "auto" }}>
                    <div className="title">{g.title}</div>
                    <div className="desc">{g.desc}</div>
                  </div>
                  <div className="foot">
                    <div className="m">pact</div>
                    <div className="m">
                      {i === CUSTOM_INDEX ? "+" : String(i + 1).padStart(2, "0")}
                    </div>
                  </div>
                </div>
              </div>
            ))}

            {/* Detail / pact card */}
            <div className="pc-detail-wrap">
              <div
                className="pc-detail"
                style={detailStyle()}
                onClick={() => {
                  if (stage === 0) select(active);
                }}
              >
                <div className="texture" />
                <div className="inner">
                  {/* header */}
                  <div className="head">
                    <div className="left">
                      <div className="ic">{goalCard.icon}</div>
                      <div>
                        <div className="goal-name">{goalName}</div>
                        <div className="goal-no m">Pact · No. 001</div>
                      </div>
                    </div>
                  </div>

                  <div className="pc-divider" />

                  <div className="pc-zones" style={{ opacity: zonesShown ? 1 : 0 }}>
                    {/* ZONE: FREQUENCY */}
                    <div className={zoneClass(1)}>
                      <div className="pc-zone-label">Frequency</div>

                      {stage === 1 && !freqUp && <FreqShimmer />}

                      {stage === 1 && freqUp && (
                        <div>
                          {isCustom && (
                            <input
                              className="pc-custom-input"
                              placeholder="Name your goal…"
                              value={customTitle}
                              autoFocus
                              maxLength={60}
                              onChange={(e) => setCustomTitle(e.target.value)}
                            />
                          )}
                          <div className="pc-freq-top">
                            <div className="pc-freq-num">
                              <div className="n m">{days}</div>
                              <div className="u">
                                days
                                <br />a week
                              </div>
                            </div>
                            <div className="pc-step-btns">
                              <div
                                className="pc-step-btn minus"
                                onClick={() => setDays((d) => Math.max(1, d - 1))}
                              >
                                −
                              </div>
                              <div
                                className="pc-step-btn plus"
                                onClick={() => setDays((d) => Math.min(7, d + 1))}
                              >
                                +
                              </div>
                            </div>
                          </div>
                          <div className="pc-bars">
                            {[1, 2, 3, 4, 5, 6, 7].map((n) => (
                              <div
                                key={n}
                                className={`pc-bar ${days >= n ? "on" : ""}`}
                              />
                            ))}
                          </div>
                          <div className="pc-divider" style={{ margin: "16px 0 0" }} />
                          <div className="pc-sub-label m">Commit for</div>
                          <div className="pc-week-pills">
                            {WEEK_OPTIONS.map((w) => (
                              <div
                                key={w}
                                className={`pc-pill ${weeks === w ? "sel" : ""}`}
                                onClick={() => setWeeks(w)}
                              >
                                {w} {w === 1 ? "wk" : "wks"}
                              </div>
                            ))}
                          </div>
                          <div className="pc-checkins m">
                            = {checkins} check-ins over the pact
                          </div>
                        </div>
                      )}

                      {stage > 1 && (
                        <div className="pc-done-tags">
                          <span className="pc-done-tag m">{days}× / week</span>
                          <span className="pc-done-tag m">
                            {weeks} {weeksWord}
                          </span>
                        </div>
                      )}
                    </div>

                    {/* ZONE: STAKE */}
                    <div className={zoneClass(2)}>
                      <div className="pc-zone-label">On the line</div>

                      {stage < 2 && (
                        <div
                          className="pc-sk"
                          style={{ marginTop: 9, width: 150, height: 42, borderRadius: 10 }}
                        />
                      )}

                      {stage === 2 && (
                        <div>
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
                              <div
                                key={v}
                                className={`pc-pill ${stake === v ? "sel" : ""}`}
                                onClick={() => setStake(v)}
                              >
                                ${v}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {stage > 2 && <div className="pc-stake-done m">${stake}</div>}
                    </div>

                    {/* ZONE: CHARITY / STAMP */}
                    <div className={zoneClass(3)}>
                      <div className="pc-zone-label">If you miss, it goes to</div>

                      {stage < 3 && (
                        <div className="pc-chips">
                          {[0, 1, 2, 3, 4].map((i) => (
                            <div
                              key={i}
                              className="pc-sk"
                              style={{ width: 36, height: 36, borderRadius: "50%" }}
                            />
                          ))}
                        </div>
                      )}

                      {stage === 3 && (
                        <div>
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
                            {charity
                              ? `${charity.name} · ${charity.category.replace(/_/g, " ")}`
                              : "Tap a cause to stamp it on"}
                          </div>
                        </div>
                      )}

                      {stage > 3 && charity && (
                        <div className="pc-charity-done">
                          <img className="pc-done-stamp" src={charity.stamp} alt={charity.name} />
                          <span className="nm">{charity.name}</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* footer signature */}
                  <div className="pc-sig">
                    <div className="pact">pact</div>
                    <div className="binding m">Binding once signed</div>
                  </div>
                </div>

                {/* Wax stamp badge — the selected charity's real stamp */}
                <div
                  className="pc-stamp"
                  style={{
                    opacity: charity ? 1 : 0,
                    transform: charity
                      ? "rotate(-9deg) scale(1)"
                      : "rotate(-9deg) scale(1.5)",
                  }}
                >
                  {charity && (
                    <img className="pc-stamp-img" src={charity.stamp} alt={charity.name} />
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Carousel arrows */}
        <button
          className="pc-arrow prev"
          onClick={prev}
          disabled={active === 0}
          style={{ opacity: stage === 0 ? 1 : 0, pointerEvents: stage === 0 ? "auto" : "none" }}
          aria-label="Previous card"
        >
          <Chevron dir="l" />
        </button>
        <button
          className="pc-arrow next"
          onClick={next}
          disabled={active === GOALS.length - 1}
          style={{ opacity: stage === 0 ? 1 : 0, pointerEvents: stage === 0 ? "auto" : "none" }}
          aria-label="Next card"
        >
          <Chevron dir="r" />
        </button>

        {/* Choose pill */}
        <button
          className="pc-choose"
          onClick={() => select(active)}
          style={{
            opacity: chooseVisible ? 1 : 0,
            pointerEvents: chooseVisible ? "auto" : "none",
          }}
        >
          Choose this card <Arrow size={17} />
        </button>

        {/* Control bar (stages 1–3) */}
        <div
          className="pc-bar"
          style={{ opacity: barVisible ? 1 : 0, pointerEvents: barVisible ? "auto" : "none" }}
        >
          <div className="step m">{stepName}</div>
          <button
            className="pc-continue"
            onClick={advance}
            disabled={stage === 3 && !charityId}
          >
            {stage === 3 ? "Seal it" : "Continue"} <Arrow />
          </button>
        </div>

        {/* Agent panel (stage 4) */}
        <div
          className="pc-agents"
          style={{
            opacity: stage === 4 ? 1 : 0,
            transform: stage === 4 ? "translateY(0)" : "translateY(18px)",
            pointerEvents: stage === 4 ? "auto" : "none",
          }}
        >
          <div className="ahead">
            <h2>Who's keeping you honest?</h2>
            <p>Your agent verifies proof and coaches you. Pick one to seal the pact.</p>
          </div>
          <div className="pc-agent-grid">
            <div className="pc-agent" onClick={() => pickAgent("Hermes")}>
              <div className="ic dark">
                <Spark />
              </div>
              <div className="nm">Hermes</div>
              <div className="dn">Your built-in coach</div>
              <div className="tag rec m">Recommended</div>
            </div>
            <div className="pc-agent" onClick={() => pickAgent("Claude Code")}>
              <div className="ic light">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width="22" height="22">
                  <path d="M8 7l-5 5 5 5M16 7l5 5-5 5" />
                </svg>
              </div>
              <div className="nm">Claude Code</div>
              <div className="dn">From your dev workflow</div>
              <div className="tag connect m">Connect</div>
            </div>
            <div className="pc-agent" onClick={() => pickAgent("your agent")}>
              <div className="ic light">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width="22" height="22">
                  <rect x="4" y="4" width="16" height="16" rx="4" />
                  <path d="M9 12h6M12 9v6" />
                </svg>
              </div>
              <div className="nm">Your own agent</div>
              <div className="dn">Any MCP agent, via API</div>
              <div className="tag connect m">Connect</div>
            </div>
          </div>
        </div>

        {/* Sending (stage 5) */}
        <div className="pc-sending" style={{ opacity: stage === 5 ? 1 : 0 }}>
          <div className="pill">
            <span className="txt m">Handing your pact to {agentName}</span>
            <span className="pc-dots">
              <span />
              <span />
              <span />
            </span>
          </div>
        </div>

        {/* Message (stage 6) */}
        <div
          className="pc-msg"
          style={{
            opacity: stage === 6 ? 1 : 0,
            pointerEvents: stage === 6 ? "auto" : "none",
          }}
        >
          <div
            className="card"
            style={{ transform: stage === 6 ? "translateY(0)" : "translateY(14px)" }}
          >
            <div className="head">
              <div className="ic">
                <Spark size={22} />
              </div>
              <div>
                <div className="nm">{agentName}</div>
                <div className="status">
                  <span className="dot" />
                  Now coaching your pact
                </div>
              </div>
            </div>
            <div className="body">
              <div className="bubble">
                Let's go — we've got a pact. <b>${stake}</b> is on the line behind{" "}
                <b>{goalName.toLowerCase()}</b>, {freqSummary}. I'll get you started: your{" "}
                <b>first check-in is tomorrow</b>. Miss it and{" "}
                {charity?.name || "your charity"} gets paid — so let's not.
              </div>
              <div className="actions">
                <button className="open" onClick={openPact}>
                  Open my pact <Arrow />
                </button>
                <button className="replay" onClick={restart}>
                  Replay
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Error toast */}
        {error && (
          <div className="pc-error">
            <span>{error}</span>
            <span className="x" onClick={() => setError(null)}>
              ✕
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// Frequency shimmer skeleton — mirrors the prototype's loading reveal.
function FreqShimmer() {
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <div className="pc-sk" style={{ width: 104, height: 36 }} />
        <div style={{ display: "flex", gap: 8 }}>
          <div className="pc-sk" style={{ width: 40, height: 40, borderRadius: 12 }} />
          <div className="pc-sk" style={{ width: 40, height: 40, borderRadius: 12 }} />
        </div>
      </div>
      <div style={{ marginTop: 14, display: "flex", gap: 5 }}>
        {[0, 1, 2, 3, 4, 5, 6].map((i) => (
          <div key={i} className="pc-sk" style={{ flex: 1, height: 30, borderRadius: 7 }} />
        ))}
      </div>
      <div style={{ marginTop: 16, height: 1, background: "var(--pc-card-line)" }} />
      <div className="pc-sk" style={{ marginTop: 14, width: 72, height: 11, borderRadius: 5 }} />
      <div style={{ marginTop: 11, display: "flex", gap: 6 }}>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="pc-sk" style={{ flex: 1, height: 42, borderRadius: 10 }} />
        ))}
      </div>
    </div>
  );
}

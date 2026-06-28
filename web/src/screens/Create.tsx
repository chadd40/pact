import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, DEMO_OWNER } from "../api";
import { useDemo } from "../App";
import type { Charity, Pact } from "../types";
import { LandingLogoMenu, PACT_DOWNLOAD_URL, type LandingMenuTarget } from "../components/LandingLogoMenu";
import { PasteWebPact } from "../components/PasteWebPact";
import { isDesktop } from "../lib/platform";
import { encodeDraft } from "../lib/handoff";
import type { PactDraft } from "../lib/handoff";
import { CC_TOP, CC_GLYPH, CC_SUBTITLE, CC_PACT, CC_INDEX, CC_GRAD } from "./customCardFrame";
import { asset } from "../lib/asset";
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

// `art` is display-only (it's never persisted — the seal sends `template`), so
// resolve it against the Vite base here. `template` and `card_art` stay raw.
const GOALS: GoalCard[] = [
  { title: "Work out", desc: "Move your body", template: "workout", art: asset("/cards/workout.svg") },
  { title: "Read", desc: "Feed your mind", template: "read", art: asset("/cards/read.svg") },
  { title: "Ship something", desc: "Build in public", template: "ship_daily", art: asset("/cards/ship.svg") },
  { title: "Meditate", desc: "Find some quiet", template: "meditate", art: asset("/cards/meditate.svg") },
  { title: "No phone at night", desc: "Reclaim your evenings", template: "no_phone_night", art: asset("/cards/nophone.svg") },
  { title: "Custom goal", desc: "Make your own", template: null, art: null },
];
const CUSTOM_INDEX = GOALS.length - 1;

// Painterly card fronts a custom goal can wear (picked via the image button on
// step 1). The goal name is overlaid at the bottom, mirroring the template cards.
// Kept as raw `/create/*` paths: the chosen one is persisted as the pact's
// `card_art`, so it must NOT carry the Vite base here (cardArtFor() / the display
// sites resolve it against the base exactly once at the point of use — prefixing
// here too would double it under a subpath like /pact/).
const CUSTOM_ARTS = [
  "/create/create_1.png",
  "/create/create_2.png",
  "/create/create_3.png",
  "/create/create_4.png",
  "/create/create_5.png",
];

// Shown as the signature line on the card back. Until accounts exist, the signer's
// real name isn't known at creation time — show a placeholder. Swap to the
// registered user's name here once that's available.
const OWNER_NAME = "Your Name";

// Agents the card can be "kept honest by".
export interface AgentDef {
  key: string;
  name: string; // as written on the card back
  blurb: string;
  avatar: string | null; // image, else a glyph tile
  tag: "rec" | "connect";
  glyph?: JSX.Element;
}
// `avatar` is display-only (the persisted agent is `key`), so resolve it against
// the Vite base here — every consumer (Create rail/final screen, PactWorld) reads
// `avatar` directly and none re-prefix.
export const AGENTS: AgentDef[] = [
  { key: "Hermes", name: "Hermes Agent", blurb: "Your built-in coach", avatar: asset("/agents/Hermes.svg"), tag: "rec" },
  { key: "Claude Code", name: "Claude Code", blurb: "From your dev workflow", avatar: asset("/agents/Claude.svg"), tag: "connect" },
  { key: "your agent", name: "Your own agent", blurb: "Any MCP agent, via API", avatar: asset("/agents/Nemoclaw.svg"), tag: "connect" },
];

// Stages: 0 deck · 1 frequency · 2 stake · 3 charity · 4 agent · 5 name · 6 sealing · 7 message
type Stage = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7;

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
const PictureIcon = ({ size = 19 }: { size?: number }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width={size} height={size}>
    <rect x="3" y="4" width="18" height="16" rx="2.5" />
    <circle cx="8.5" cy="9.5" r="1.6" />
    <path d="M21 16l-5-5L5 20" />
  </svg>
);
const DownloadIcon = ({ size = 18 }: { size?: number }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width={size} height={size}>
    <path d="M12 4v11m0 0l-4-4m4 4l4-4M5 19h14" />
  </svg>
);

// Custom-goal card front, built from the designer's custom_card.svg frame: the
// chosen picture fills the top window (the images are 1130×1121, the exact window
// size, so they land 1:1 top-aligned) and the goal title replaces [GOAL_TEXT] as
// live Geist text (auto-shrunk to stay on one line in the ~900px column).
export function CustomCardFront({ imageSrc, title }: { imageSrc: string; title: string }) {
  const t = (title || "").trim() || "Your goal";
  const fontSize = Math.max(46, Math.min(104, Math.round(900 / Math.max(1, t.length * 0.58))));
  return (
    <svg className="pc-cc-svg" viewBox="0 0 1130 1584" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet">
      <defs
        dangerouslySetInnerHTML={{
          __html: `<clipPath id="cc-top"><path d="${CC_TOP}"/></clipPath>` +
            CC_GRAD.replace(/paint0_linear_33_40/g, "cc-grad"),
        }}
      />
      <rect width="1130" height="1584" rx="74" fill="#181818" />
      <image
        href={imageSrc}
        x="0"
        y="0"
        width="1130"
        height="1121"
        clipPath="url(#cc-top)"
        preserveAspectRatio="xMidYMid slice"
      />
      <path d={CC_TOP} fill="url(#cc-grad)" />
      <rect x="111" y="120" width="160" height="160" rx="17" fill="#10100C" />
      <path d={CC_GLYPH} fill="#E8DDCD" />
      <text
        x="116"
        y="1283"
        fontFamily="Geist, system-ui, sans-serif"
        fontWeight="700"
        fontSize={fontSize}
        letterSpacing="-2"
        fill="#E8DDCD"
      >
        {t}
      </text>
      <path d={CC_SUBTITLE} fill="#D6CABA" />
      <path d={CC_PACT} fill="#81786B" />
      <path d={CC_INDEX} fill="#81786B" />
      <circle cx="228" cy="1503" r="7" fill="#b0432a" />
    </svg>
  );
}

export function Create({ embedded = false }: { embedded?: boolean } = {}) {
  const navigate = useNavigate();
  const { signalChange } = useDemo();

  const [stage, setStage] = useState<Stage>(0);
  const [active, setActive] = useState(0); // carousel focus index
  const [goalIndex, setGoalIndex] = useState<number | null>(null); // chosen card
  const [customTitle, setCustomTitle] = useState("");
  const [customDesc, setCustomDesc] = useState(""); // custom goals: "what counts"
  const [days, setDays] = useState(5);
  const [weeks, setWeeks] = useState(4);
  const [stake, setStake] = useState(200);
  const [charityId, setCharityId] = useState<string | null>(null);
  const [agentKey, setAgentKey] = useState<string | null>(null);
  const [signerName, setSignerName] = useState(""); // step 5 — signs the card
  const [customArt, setCustomArt] = useState<string | null>(null); // custom-goal front
  const [pickerOpen, setPickerOpen] = useState(false); // image picker open
  const [peeking, setPeeking] = useState(false); // momentary flip-to-front peek
  const peekTimer = useRef<number | null>(null);
  // Reveal beat: after the flip lands, the card "loads" — title + frequency
  // resolve out of the skeleton and the editor rail comes alive.
  const [editorReady, setEditorReady] = useState(false);

  const [charities, setCharities] = useState<Charity[]>([]);
  const [created, setCreated] = useState<Pact | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Web-mode handoff: clipboard copy state.
  const [copied, setCopied] = useState(false);
  const [blobText, setBlobText] = useState<string | null>(null);

  const stageRef = useRef(stage);
  stageRef.current = stage;

  // Import a draft from the web → prefill the flow and land on the agent step.
  // stake_amount_cents ÷ 100 → dollars (the seal handler writes stake * 100).
  // If the draft carries a goal_template, find the matching GOALS card and restore
  // it as a template goal (same card index as a manually picked one). Otherwise
  // fall back to the custom-goal path (CUSTOM_INDEX + free-text title/what_counts).
  const importDraft = (d: PactDraft) => {
    const templateIndex = d.goal_template
      ? GOALS.findIndex((g) => g.template === d.goal_template)
      : -1;
    if (templateIndex >= 0) {
      // Template goal: restore the exact card. Mirror what select() does for a
      // non-custom card — set goalIndex + active, leave customTitle/customDesc blank.
      setGoalIndex(templateIndex);
      setActive(templateIndex);
      setCustomTitle("");
      setCustomDesc("");
    } else {
      // Custom goal: treat the goal string as free text.
      setGoalIndex(CUSTOM_INDEX);
      setActive(CUSTOM_INDEX);
      setCustomTitle(d.goal);
      setCustomDesc(d.what_counts ?? "");
    }
    setDays(d.frequency.days_per_week);
    setWeeks(d.frequency.weeks);
    setStake(Math.round(d.stake_amount_cents / 100));
    setCharityId(d.charity_id);
    setAgentKey(d.agent);
    setSignerName(d.signer_name ?? "");
    setCustomArt(d.card_art ?? null);
    setEditorReady(true);
    // Everything but the signature is filled — land on the name step ready to sign.
    setStage(5);
  };

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
      const pad = 28;
      if (embedded) {
        // Fit the fixed world into the embedding container's own box (the landing
        // sizes it via CSS) — stable regardless of page scroll position.
        const w = el.clientWidth - pad;
        const h = el.clientHeight - pad;
        const scale = Math.min(w / STAGE_W, h / STAGE_H, 1);
        el.style.setProperty("--pc-scale", String(Math.max(scale, 0.3)));
        return;
      }
      const top = el.getBoundingClientRect().top;
      const avail = window.innerHeight - top;
      el.style.minHeight = `${avail}px`;
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
  }, [embedded]);

  // Move keyboard focus onto the active surface when the stage changes, so focus
  // is never stranded on hidden deck controls.
  const railHeadRef = useRef<HTMLHeadingElement>(null);
  const openBtnRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if ((stage === 1 && isCustom) || stage === 5) return; // name inputs auto-focus themselves
    // When embedded on the landing, never let focus yank the page-scroll around.
    if (stage >= 1 && stage <= 5) railHeadRef.current?.focus({ preventScroll: embedded });
    else if (stage === 7) openBtnRef.current?.focus({ preventScroll: embedded });
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
    setCustomDesc("");
    setCustomArt(null);
    setPickerOpen(false);
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

  // Click anywhere on a card. In the deck it picks/recenters; while editing,
  // clicking the chosen card flips it to its front for a beat so you can see the
  // image + goal, then it smoothly flips back.
  const onCardClick = (i: number) => {
    if (stage === 0) {
      tap(i);
      return;
    }
    if (i === goalIndex && stage >= 1 && stage <= 5) peekFront();
  };

  const peekFront = () => {
    setPeeking(true);
    if (peekTimer.current) window.clearTimeout(peekTimer.current);
    peekTimer.current = window.setTimeout(() => setPeeking(false), 1300);
  };
  useEffect(() => () => { if (peekTimer.current) window.clearTimeout(peekTimer.current); }, []);

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
    if (stage === 4 && !agentKey) return;
    setStage((s) => Math.min(5, (s + 1) as Stage) as Stage);
  };

  const seal = async () => {
    if (!charityId || !agentKey) return;
    if (stageRef.current >= 6) return; // guard against double-seal (duplicate pacts)
    setError(null);
    setStage(6);
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
        description: isCustom ? customDesc.trim() || undefined : undefined,
        card_art: isCustom ? customArt ?? undefined : undefined,
        signer_name: signerName.trim() || undefined,
      });
      setCreated(pact);
      signalChange();
      window.setTimeout(() => setStage(7), 1300);
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail : "Could not seal the pact. Try again.";
      setError(detail);
      setStage(5);
    }
  };

  const openPact = () => {
    if (created) {
      if (isDesktop()) {
        navigate("/onboard", { state: { pactId: created.id } });
      } else {
        navigate(`/pact/${created.id}`);
      }
    }
  };

  const goToLanding = (target: LandingMenuTarget) => {
    navigate("/", { state: { scrollTo: target } });
  };

  // Encode the current choices into a copy-paste handoff blob. Mirrors the seal
  // handler's goal/what_counts derivation exactly so the desktop side receives a
  // faithful pact definition (now including the signer's name).
  const buildBlob = (): string | null => {
    if (!charityId || !agentKey) return null;
    const draft: PactDraft = {
      goal: goalName,
      ...(isCustom ? {} : { goal_template: goalCard.template ?? undefined }),
      what_counts: isCustom ? customDesc.trim() || undefined : undefined,
      frequency: { days_per_week: days, weeks },
      stake_amount_cents: stake * 100,
      charity_id: charityId,
      agent: agentKey,
      signer_name: signerName.trim() || undefined,
      card_art: isCustom ? customArt ?? undefined : undefined,
    };
    return encodeDraft(draft);
  };

  // Web mode "Sign the pact": there's no local account to seal into, so we encode
  // the handoff blob, play the signing beat, then land on the download + paste
  // screen the user finishes in the desktop app.
  const signWeb = () => {
    if (!charityId || !agentKey || !signerName.trim()) return;
    if (stageRef.current >= 6) return;
    setError(null);
    setCopied(false);
    const blob = buildBlob();
    if (!blob) return;
    setBlobText(blob);
    setStage(6);
    window.setTimeout(() => setStage(7), 1300);
  };

  // Copy the handoff blob from the final screen.
  const copyBlob = async () => {
    if (!blobText) return;
    try {
      await navigator.clipboard.writeText(blobText);
      setCopied(true);
    } catch {
      setCopied(false); // clipboard blocked — the textarea is there for manual copy
    }
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
      const exiting = stage >= 6;
      return {
        transform: slotTransform(-258, exiting ? 44 : 0, 60, 0, exiting ? 0.86 : 1),
        opacity: stage === 7 ? 0 : 1,
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
    // The chosen card shows its editorial back while editing — except during a
    // peek, when it flips back to the front for a beat.
    const flipped = stage >= 1 && i === goalIndex && !peeking;
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
  const signed = stage >= 6;
  const zoneState = (n: number) => (stage === n ? "active" : stage > n ? "done" : "pending");

  const deckMode = stage === 0;
  const editing = stage >= 1 && stage <= 5;

  // ── Editor rail step copy ────────────────────────────────────────────────────
  const stepMeta =
    stage === 1
      ? { n: 1, head: isCustom ? "Name it & set the pace" : "Set the pace" }
      : stage === 2
      ? { n: 2, head: "Put it on the line" }
      : stage === 3
      ? { n: 3, head: "Choose the cause" }
      : stage === 4
      ? { n: 4, head: "Pick your agent" }
      : stage === 5
      ? { n: 5, head: "Sign your name" }
      : { n: 0, head: "" };

  const canContinue =
    stage === 1
      ? !isCustom || !!customTitle.trim()
      : stage === 3
      ? !!charityId
      : stage === 4
      ? !!agentKey
      : true;

  return (
    <div className={embedded ? "pc-root pc-embedded" : "pc-root"} ref={rootRef}>
      {/* Top-left chrome lives outside the scaled stage. Web reuses the landing
          dropdown menu; desktop keeps its existing brand lockup + paste slot. */}
      {!embedded && (
        isDesktop() ? (
          <button type="button" className="pc-brand" onClick={() => navigate("/")} aria-label="Pact, back to home">
            <img className="pc-brand-logo" src={asset("/primary_logo.svg")} alt="Pact" />
          </button>
        ) : (
          <LandingLogoMenu onGoTo={goToLanding} />
        )
      )}
      {isDesktop() && stage === 0 && (
        <div className="pc-paste-slot">
          <PasteWebPact onImport={importDraft} />
        </div>
      )}

      {/* Full-page ambient vignette — lives outside the scaled stage so it covers
          the whole viewport, not just the stage box. */}
      <div className="pc-vignette" />

      <div className="pc-stage">
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
                  onClick={() => onCardClick(i)}
                  onKeyDown={(e) => {
                    if (deckMode && (e.key === "Enter" || e.key === " ")) {
                      e.preventDefault();
                      tap(i);
                    }
                  }}
                  role={deckMode ? "button" : undefined}
                  tabIndex={deckMode ? 0 : -1}
                  aria-hidden={!deckMode && !isHero}
                  aria-label={deckMode ? `${g.title}: ${g.desc}` : undefined}
                >
                  <div className="pc-flip" style={flipStyle(i)}>
                    {/* FRONT */}
                    <div className="pc-face pc-front">
                      {g.art ? (
                        <img className="pc-art" src={g.art} alt="" draggable={false} />
                      ) : isHero && customArt ? (
                        // Custom goal with a picked picture: the designer's card
                        // frame with the image + live goal title.
                        <CustomCardFront imageSrc={asset(customArt)} title={goalName} />
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
                          owner={signerName.trim() || OWNER_NAME}
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
            <div className="m step">Step {stepMeta.n} of 5</div>
            <h2 ref={railHeadRef} tabIndex={-1}>{stepMeta.head}</h2>
          </div>

          <div className="pc-rail-body">
            {/* FREQUENCY */}
            {stage === 1 && (
              <div className="pc-panel">
                {isCustom && (
                  <>
                    <div className="pc-name-row">
                      <input
                        className="pc-name-input"
                        placeholder="Name your goal…"
                        aria-label="Name your goal"
                        value={customTitle}
                        autoFocus
                        maxLength={60}
                        onChange={(e) => setCustomTitle(e.target.value)}
                      />
                      <button
                        type="button"
                        className={`pc-art-btn${customArt ? " has" : ""}`}
                        aria-label="Choose a picture for your card"
                        aria-expanded={pickerOpen}
                        onClick={() => setPickerOpen((o) => !o)}
                      >
                        <PictureIcon />
                      </button>
                    </div>
                    {pickerOpen && (
                      <div className="pc-art-picker" role="listbox" aria-label="Card pictures">
                        {CUSTOM_ARTS.map((src, idx) => (
                          <button
                            key={src}
                            type="button"
                            role="option"
                            aria-selected={customArt === src}
                            className={`pc-art-opt${customArt === src ? " sel" : ""}`}
                            onClick={() => {
                              setCustomArt(src);
                              setPickerOpen(false);
                            }}
                          >
                            <img src={asset(src)} alt={`Card picture ${idx + 1}`} loading="lazy" />
                          </button>
                        ))}
                      </div>
                    )}
                    <textarea
                      className="pc-desc-input"
                      placeholder="What counts as a check-in? (optional, your agent judges against this)"
                      aria-label="What counts as a check-in"
                      value={customDesc}
                      maxLength={140}
                      rows={2}
                      onChange={(e) => setCustomDesc(e.target.value)}
                    />
                  </>
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
                <div className="pc-charity-info">
                  {charity ? (
                    <>
                      <div className="pc-charity-name">{charity.name}</div>
                      <p className="pc-charity-desc">{charity.description}</p>
                    </>
                  ) : (
                    <div className="pc-charity-prompt m">Tap a cause to stamp it on</div>
                  )}
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

            {/* NAME — signs the card */}
            {stage === 5 && (
              <div className="pc-panel">
                <input
                  className="pc-name-input pc-signer-input"
                  placeholder="Your name…"
                  aria-label="Your name"
                  value={signerName}
                  autoFocus
                  maxLength={40}
                  onChange={(e) => setSignerName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && signerName.trim()) (isDesktop() ? seal : signWeb)();
                  }}
                />
                <div className="pc-help m">
                  This is the name that signs your pact. It's written on the card and stands behind the promise.
                </div>
              </div>
            )}
          </div>

          <div className="pc-rail-foot">
            {stage < 5 ? (
              <button className="pc-continue" onClick={advance} disabled={!canContinue}>
                Continue <Arrow />
              </button>
            ) : (
              /* Step 5: sign. Desktop seals locally; web emits the handoff + lands on
                 the download screen. */
              <button
                className="pc-continue seal"
                onClick={isDesktop() ? seal : signWeb}
                disabled={!signerName.trim()}
              >
                Sign the pact <Arrow />
              </button>
            )}
          </div>
        </div>

        {/* Sealing (stage 6) */}
        <div className="pc-sending" style={{ opacity: stage === 6 ? 1 : 0 }}>
          <div className="pill">
            <span className="txt m">Signing your pact with {agentDef?.name || "your agent"}</span>
            <span className="pc-dots"><span /><span /><span /></span>
          </div>
        </div>

        {/* Final screen (stage 7) */}
        <div
          className="pc-msg"
          style={{ opacity: stage === 7 ? 1 : 0, pointerEvents: stage === 7 ? "auto" : "none" }}
        >
          <div className="card" style={{ transform: stage === 7 ? "translateY(0)" : "translateY(14px)" }}>
            {isDesktop() && created ? (
              <>
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
                    Let's go, we've got a pact. <b>${stake}</b> is on the line behind{" "}
                    <b>{goalName.toLowerCase()}</b>, {days} days/week for {weeks} {weeksWord}. I'll get you
                    started: your <b>first check-in is tomorrow</b>. Miss it and{" "}
                    {charity?.name || "your charity"} gets paid, so let's not.
                  </div>
                  <div className="actions">
                    <button className="open" ref={openBtnRef} onClick={openPact}>
                      Open my pact <Arrow />
                    </button>
                  </div>
                </div>
              </>
            ) : (
              /* Web: the pact is signed but lives in the copy-paste blob. Send the
                 user to the app — download it, then paste the pact in. */
              <>
                <div className="head pc-done-head">
                  <div className="ic done">
                    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                  <div>
                    <div className="nm">Pact signed by {signerName.trim() || "you"}</div>
                    <div className="status">
                      <span className="dot" />${stake} on {goalName.toLowerCase()} · {days}×/wk · {weeks} {weeksWord}
                    </div>
                  </div>
                </div>
                <div className="body">
                  <p className="pc-done-lede">
                    Two steps to put it on the line: get the Pact app, then paste your signed pact in.
                  </p>
                  <div className="pc-done-steps">
                    <a className="pc-done-download" href={PACT_DOWNLOAD_URL} target="_blank" rel="noreferrer">
                      <DownloadIcon /> Download the app
                    </a>
                    <button className="pc-done-copy" onClick={copyBlob}>
                      {copied ? "Copied, now paste it in ✓" : "Copy your pact"}
                    </button>
                  </div>
                  <textarea
                    className="pc-handoff-blob pc-done-blob"
                    readOnly
                    value={blobText ?? ""}
                    rows={3}
                    aria-label="Pact payload: copy and paste this into the Pact desktop app"
                    onClick={(e) => (e.target as HTMLTextAreaElement).select()}
                  />
                </div>
              </>
            )}
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
export interface CardBackProps {
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

export function CardBack(p: CardBackProps) {
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

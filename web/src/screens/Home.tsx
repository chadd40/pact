import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { motion } from "motion/react";
import { api, DEMO_OWNER } from "../api";
import { useDemo } from "../App";
import { useAppData } from "../data";
import { dollars, formatDate } from "../lib";
import { cardArtFor } from "../lib/cardArt";
import { statusDot } from "../lib/pactStatus";
import { pickStatement } from "../lib/motivation";
import { GoalGlyph } from "../components/GoalGlyph";
import { CustomCardFront } from "./Create";
import type { Charity, Pact, Profile } from "../types";

const STEP = 210;
const CAROUSEL = new Set(["active", "evaluating"]);

function greeting(nowMs: number): string {
  const h = new Date(nowMs).getHours();
  const part = h < 5 ? "Late night" : h < 12 ? "Morning" : h < 17 ? "Afternoon" : h < 21 ? "Evening" : "Night";
  const day = new Date(nowMs).toLocaleDateString("en-US", { weekday: "long" });
  return `${day} ${part.toLowerCase()}`;
}

const CheckIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" width="14" height="14">
    <path d="M5 12.5 10 17l9-11" />
  </svg>
);
const HazardIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="14" height="14">
    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
    <line x1="12" y1="9" x2="12" y2="13" />
    <line x1="12" y1="17" x2="12.01" y2="17" />
  </svg>
);
const AlertIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="14" height="14">
    <circle cx="12" cy="12" r="10" />
    <line x1="12" y1="8" x2="12" y2="12" />
    <line x1="12" y1="16" x2="12.01" y2="16" />
  </svg>
);

export function Home() {
  const { bump, nowIso } = useDemo();
  const { pacts: allPacts, pactsLoaded, charityById } = useAppData();
  const navigate = useNavigate();
  const location = useLocation();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [statement] = useState(() => pickStatement());

  // carousel state
  const [active, setActive] = useState(0);
  const [drag, setDrag] = useState<{ dx: number } | null>(null);
  const dragInfo = useRef<{ startX: number; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  const tiltRef = useRef<HTMLDivElement>(null);

  // Pacts + charities come from the shared AppData (fetched once by AppShell).
  // Only the profile is Home-specific; refresh it on the demo bump.
  useEffect(() => {
    let alive = true;
    api.profile(DEMO_OWNER).then((p) => alive && setProfile(p)).catch(() => {});
    return () => { alive = false; };
  }, [bump]);

  // Global pointer listeners drive the drag (mirrors the mockup's window handlers).
  useEffect(() => {
    const move = (e: PointerEvent) => {
      if (!dragInfo.current) return;
      const dx = e.clientX - dragInfo.current.startX;
      if (Math.abs(dx) > 4) dragInfo.current.moved = true;
      setDrag({ dx });
    };
    const up = () => {
      if (!dragInfo.current) return;
      setDrag((d) => {
        setActive((a) => {
          const na = d ? Math.round(a - d.dx / STEP) : a;
          return Math.max(0, Math.min(cardCount.current - 1, na));
        });
        return null;
      });
      const moved = dragInfo.current.moved;
      dragInfo.current = null;
      if (moved) { suppressClick.current = true; setTimeout(() => { suppressClick.current = false; }, 90); }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  }, []);

  const all = [...allPacts].sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at));
  const carousel = all.filter((p) => CAROUSEL.has(p.status));
  const ledger = all.filter((p) => !CAROUSEL.has(p.status) && p.status !== "draft");
  const cardCount = useRef(0);
  cardCount.current = carousel.length + 1; // +1 for the "New pact" card

  // ledger win-rate (used in ledger sub-head)
  const kept = profile?.kept ?? 0;
  const failed = profile?.failed ?? 0;
  const winRate = kept + failed > 0 ? Math.round((100 * kept) / (kept + failed)) : null;

  const openPact = (id: string) => {
    if (suppressClick.current) return;
    navigate(`/pact/${id}`, { state: { backgroundLocation: location } });
  };

  const onDown = (e: React.PointerEvent) => {
    dragInfo.current = { startX: e.clientX, moved: false };
    setDrag({ dx: 0 });
  };
  const onTilt = (e: React.MouseEvent) => {
    if (dragInfo.current) return;
    const el = tiltRef.current;
    if (!el) return;
    const r = e.currentTarget.getBoundingClientRect();
    const nx = ((e.clientX - r.left) / r.width - 0.5) * 2;
    const ny = ((e.clientY - r.top) / r.height - 0.5) * 2;
    el.style.transform = `rotateY(${(nx * 5).toFixed(2)}deg) rotateX(${(-ny * 4).toFixed(2)}deg)`;
  };
  const onLeave = () => { if (tiltRef.current) tiltRef.current.style.transform = ""; };
  const step = (dir: number) => setActive((a) => Math.max(0, Math.min(cardCount.current - 1, a + dir)));
  const onStageKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
    else if (e.key === "ArrowRight") { e.preventDefault(); step(1); }
  };

  const cardStyle = (i: number): React.CSSProperties => {
    const frac = drag ? drag.dx / STEP : 0;
    const off = i - (active - frac);
    const ao = Math.abs(off);
    const tx = off * STEP, tz = -ao * 120, ry = off * -22, sc = Math.max(0.6, 1 - ao * 0.09);
    const op = ao > 3.8 ? 0 : 1;
    const tr = drag
      ? "transform 0s, opacity .3s ease"
      : "transform .55s cubic-bezier(.32,.62,.3,1), opacity .45s ease";
    return {
      transform: `translate(-50%,-50%) translateX(${tx.toFixed(1)}px) translateZ(${tz.toFixed(1)}px) rotateY(${ry.toFixed(1)}deg) scale(${sc.toFixed(3)})`,
      opacity: op,
      zIndex: 100 - Math.round(ao * 10),
      transition: tr,
    };
  };

  return (
    <div className="home">
      <div className="home-head">
        <div>
          <div className="home-eyebrow m">{greeting(nowIso ? new Date(nowIso).getTime() : Date.now())}</div>
          <div className="home-headline">{statement}</div>
        </div>
      </div>

      {/* ── Carousel shelf ── */}
      <div className="home-shelf">
        <div className="home-shelf-label m">Active pacts · click a card to open it</div>
        <div className="home-stage" role="group" aria-label="Active pacts carousel — use left and right arrow keys, or click a card" onKeyDown={onStageKey} onPointerDown={onDown} onMouseMove={onTilt} onMouseLeave={onLeave}>
          <div className="home-tilt" ref={tiltRef}>
            {carousel.map((p, i) => {
              const art = cardArtFor(p);
              const dot = statusDot(p);
              return (
                <div
                  key={p.id}
                  role="button"
                  tabIndex={0}
                  aria-label={`Open ${p.title} — ${dollars(p.stake_amount_cents)} on the line`}
                  className="home-card real"
                  style={cardStyle(i)}
                  onClick={() => openPact(p.id)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openPact(p.id); } }}
                >
                  <motion.div
                    className="home-cardfront"
                    layoutId={`pact-card-${p.id}`}
                  >
                    <span
                      className={`home-dot ${dot}`}
                      aria-label={dot === "green" ? "On track" : dot === "amber" ? "At risk" : "Off track"}
                    >
                      {dot === "green" ? <CheckIcon /> : dot === "amber" ? <HazardIcon /> : <AlertIcon />}
                    </span>
                    {art.kind === "photo"
                      ? <CustomCardFront imageSrc={art.src} title={art.title} />
                      : art.kind === "art"
                      ? <img className="home-cardart" src={art.src} alt={p.title} draggable={false} />
                      : (
                        <div className="home-cardglyph">
                          <GoalGlyph title={p.title} size={40} />
                          <div className="home-cardglyph-title">{p.title}</div>
                        </div>
                      )}
                  </motion.div>
                </div>
              );
            })}
            {/* New pact card */}
            <div
              role="button"
              tabIndex={0}
              aria-label="Start a new pact"
              className="home-card new"
              style={cardStyle(carousel.length)}
              onClick={() => { if (!suppressClick.current) navigate("/create"); }}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); navigate("/create"); } }}
            >
              <div className="home-card-new-plus">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="26" height="26"><path d="M12 5v14M5 12h14" /></svg>
              </div>
              <div className="home-card-new-title">New pact</div>
              <div className="home-card-new-sub">Put something new on the line.</div>
              <div className="home-card-new-cta">
                Start one
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" width="15" height="15"><path d="M5 12h13M12 6l6 6-6 6" /></svg>
              </div>
            </div>
          </div>
          <button className="home-arrow left" onClick={() => step(-1)} aria-label="Previous">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" width="18" height="18"><path d="M15 6l-6 6 6 6" /></svg>
          </button>
          <button className="home-arrow right" onClick={() => step(1)} aria-label="Next">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" width="18" height="18"><path d="M9 6l6 6-6 6" /></svg>
          </button>
        </div>
      </div>

      {/* ── Ledger ── */}
      <div className="home-ledger">
        <div className="home-ledger-head">
          <div className="home-ledger-title">Past pacts</div>
          <div className="home-ledger-sub m">{ledger.length} closed{winRate != null ? ` · ${winRate}% kept` : ""}</div>
        </div>
        <div className="home-ledger-list">
          {!pactsLoaded ? (
            <div className="home-empty">Loading…</div>
          ) : ledger.length === 0 ? (
            <div className="home-empty">Nothing closed yet — your finished pacts will line up here.</div>
          ) : (
            ledger.map((p) => <LedgerRow key={p.id} pact={p} charity={charityById[p.charity_id]} onClick={() => navigate(`/pact/${p.id}`)} />)
          )}
        </div>
      </div>
    </div>
  );
}

function LedgerRow({ pact, charity, onClick }: { pact: Pact; charity?: Charity; onClick: () => void }) {
  const kept = pact.status === "succeeded" || pact.status === "canceled_release";
  const review = pact.status === "needs_review";
  const pending = pact.status === "donation_pending";
  const dest = kept
    ? "Kept · stake returned"
    : review
    ? "Under review"
    : pending
    ? `Donation due · ${charity?.name ?? "charity"}`
    : `Donated · ${charity?.name ?? "charity"}`;
  return (
    <button className="home-row" onClick={onClick} aria-label={`${pact.title} — ${dest} — ${dollars(pact.stake_amount_cents)}`}>
      <span className={`home-row-icon ${kept ? "kept" : review ? "review" : pending ? "pending" : "missed"}`}>
        {kept ? (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" width="15" height="15"><path d="M5 12.5 10 17l9-11" /></svg>
        ) : review || pending ? (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></svg>
        ) : (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><path d="M6 6l12 12M18 6 6 18" /></svg>
        )}
      </span>
      <span className="home-row-main">
        <span className="home-row-name">{pact.title}</span>
        <span className="home-row-dest">{dest}</span>
      </span>
      <span className="home-row-when m">{formatDate(pact.verdict_at || pact.deadline_at)}</span>
      <span className="home-row-stake m">{dollars(pact.stake_amount_cents)}</span>
    </button>
  );
}

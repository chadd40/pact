import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useDemo } from "../App";
import { useAppData } from "../data";
import { dollars, formatDate } from "../lib";
import { cardArtFor } from "../lib/cardArt";
import { statusDot } from "../lib/pactStatus";
import { pickStatement } from "../lib/motivation";
import { GoalGlyph } from "../components/GoalGlyph";
import { CustomCardFront } from "./Create";
import type { Charity, Pact } from "../types";

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
  const { nowIso } = useDemo();
  const { pacts: allPacts, pactsLoaded, charityById } = useAppData();
  const navigate = useNavigate();
  const [statement] = useState(() => pickStatement());

  // carousel state
  const [active, setActive] = useState(0);
  const [drag, setDrag] = useState<{ dx: number } | null>(null);
  const dragInfo = useRef<{ startX: number; moved: boolean } | null>(null);
  const suppressClick = useRef(false);

  // Pacts + charities come from the shared AppData (fetched once by AppShell).

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

  // The "New pact" card lives at index 0, so on first load we center the newest
  // real pact (index 1) — leaving "New pact" one step to its left, a single
  // left-swipe away. With no pacts yet it's the only card, so it centers itself.
  const didCenter = useRef(false);
  useEffect(() => {
    if (!pactsLoaded || didCenter.current) return;
    didCenter.current = true;
    setActive(carousel.length > 0 ? 1 : 0);
  }, [pactsLoaded, carousel.length]);

  const openPact = (id: string, e?: React.MouseEvent | React.KeyboardEvent) => {
    if (suppressClick.current) return;
    // Clicking a card flips it open into the centered detail world (Task 8).
    // Capture the card's on-screen box so PactWorld can run a CSS/JS FLIP from
    // here to its natural centered rect. Keyboard-open passes no event → no rect
    // → the world just appears (no flip). Plain numbers keep state serializable.
    const el = e?.currentTarget as HTMLElement | undefined;
    const r = el?.getBoundingClientRect();
    const flipFrom = r ? { x: r.x, y: r.y, width: r.width, height: r.height } : undefined;
    navigate(`/pact/${id}`, flipFrom ? { state: { flipFrom } } : undefined);
  };

  const onDown = (e: React.PointerEvent) => {
    dragInfo.current = { startX: e.clientX, moved: false };
    setDrag({ dx: 0 });
  };
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
        <div className="home-stage" role="group" aria-label="Active pacts carousel — use left and right arrow keys, or click a card" onKeyDown={onStageKey} onPointerDown={onDown}>
          <div className="home-tilt">
            {/* New pact card — index 0, so it sits just left of the newest pact */}
            <div
              role="button"
              tabIndex={0}
              aria-label="Start a new pact"
              className="home-card new"
              style={cardStyle(0)}
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
                  style={cardStyle(i + 1)}
                  onClick={(e) => openPact(p.id, e)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openPact(p.id); } }}
                >
                  <div className="home-cardfront">
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
                  </div>
                </div>
              );
            })}
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
          {pactsLoaded && ledger.length > 0 && (
            <div className="home-ledger-cols" aria-hidden="true">
              <span className="home-col-when">Date</span>
              <span className="home-col-stake">Pact amount</span>
            </div>
          )}
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

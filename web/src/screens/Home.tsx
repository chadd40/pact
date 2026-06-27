import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, DEMO_OWNER } from "../api";
import { useDemo } from "../App";
import { dollars, formatDate, pactNo } from "../lib";
import type { Charity, Pact, Profile } from "../types";

const STEP = 210;
const CAROUSEL = new Set(["active", "evaluating"]);

// Map a goal title to one of the card glyphs (mirrors the mockup's icon set).
function goalGlyph(title: string) {
  const t = title.toLowerCase();
  if (/work\s?out|gym|run|exercise|lift|train|10k|cardio|yoga/.test(t)) return "dumbbell";
  if (/read|book|study|write|sketch|journal/.test(t)) return "book";
  if (/phone|screen|scroll|sleep|night|bed|wake|6am/.test(t)) return "moon";
  if (/meditat|breath|calm|quiet|plunge|cold/.test(t)) return "lotus";
  return "star";
}
function Glyph({ name }: { name: string }) {
  const p = {
    dumbbell: <path d="M3 9v6M6 7.5v9M18 7.5v9M21 9v6M6 12h12" />,
    book: <><path d="M5 4a1 1 0 0 1 1-1h12v16H6a1 1 0 0 0-1 1Z" /><path d="M18 3v16" /></>,
    moon: <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z" />,
    lotus: <path d="M5 19c8 1 14-5 14-14 0 0-13-1-13 8a6 6 0 0 0 2 6Z" />,
    star: <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8Z" />,
  }[name];
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="24" height="24">{p}</svg>
  );
}

function greeting(nowMs: number): string {
  const h = new Date(nowMs).getHours();
  const part = h < 5 ? "Late night" : h < 12 ? "Morning" : h < 17 ? "Afternoon" : h < 21 ? "Evening" : "Night";
  const day = new Date(nowMs).toLocaleDateString("en-US", { weekday: "long" });
  return `${day} ${part.toLowerCase()}`;
}

export function Home() {
  const { bump, nowMs } = useDemo();
  const navigate = useNavigate();
  const [pacts, setPacts] = useState<Pact[] | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [charities, setCharities] = useState<Record<string, Charity>>({});

  // carousel state
  const [active, setActive] = useState(0);
  const [drag, setDrag] = useState<{ dx: number } | null>(null);
  const dragInfo = useRef<{ startX: number; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  const tiltRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      const [p, prof, cats] = await Promise.all([
        api.listPacts(DEMO_OWNER).catch(() => [] as Pact[]),
        api.profile(DEMO_OWNER).catch(() => null),
        api.charities().catch(() => [] as Charity[]),
      ]);
      if (!alive) return;
      p.sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at));
      setPacts(p);
      setProfile(prof);
      setCharities(Object.fromEntries(cats.map((c) => [c.id, c])));
    })();
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

  const all = pacts ?? [];
  const carousel = all.filter((p) => CAROUSEL.has(p.status));
  const ledger = all.filter((p) => !CAROUSEL.has(p.status) && p.status !== "draft");
  const cardCount = useRef(0);
  cardCount.current = carousel.length + 1; // +1 for the "New pact" card

  // stats
  const kept = profile?.kept ?? 0;
  const failed = profile?.failed ?? 0;
  const winRate = kept + failed > 0 ? Math.round((100 * kept) / (kept + failed)) : null;
  const donated = all
    .filter((p) => p.status === "donated")
    .reduce((s, p) => s + p.stake_amount_cents, 0);
  const stats = [
    { big: String(profile?.current_streak ?? 0), label: "Current streak" },
    { big: String(profile?.best_streak ?? 0), label: "Best streak" },
    { big: winRate == null ? "—" : `${winRate}%`, label: "Win rate" },
    { big: String(carousel.length), label: "Active pacts" },
    { big: dollars(donated), label: "Donated" },
  ];

  // data-derived headline
  const atRisk = carousel.find((p) => p.progress?.behind);
  const near = carousel.find((p) => p.progress && p.progress.pct >= 80 && p.progress.pct < 100);
  let headline = "Make something binding.";
  if (atRisk) headline = `${atRisk.title} is slipping — ${dollars(atRisk.stake_amount_cents)} is on the line.`;
  else if (near) headline = "One session from a clean week.";
  else if (carousel.length) headline = `You're on track across ${carousel.length} pact${carousel.length === 1 ? "" : "s"}.`;

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
  const openCard = (id: string) => { if (suppressClick.current) return; navigate(`/pact/${id}`); };

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
          <div className="home-eyebrow m">{greeting(nowMs)}</div>
          <div className="home-headline">{headline}</div>
        </div>
        <div className="home-stats">
          {stats.map((s) => (
            <div className="home-stat" key={s.label}>
              <div className="home-stat-num m">{s.big}</div>
              <div className="home-stat-label">{s.label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Carousel shelf ── */}
      <div className="home-shelf">
        <div className="home-shelf-label m">Active pacts · click a card to open it</div>
        <div className="home-stage" role="group" aria-label="Active pacts carousel — use left and right arrow keys, or click a card" onKeyDown={onStageKey} onPointerDown={onDown} onMouseMove={onTilt} onMouseLeave={onLeave}>
          <div className="home-tilt" ref={tiltRef}>
            {carousel.map((p, i) => {
              const cad = p.cadence;
              const prog = p.progress;
              const behind = prog?.behind ?? false;
              return (
                <div
                  key={p.id}
                  role="button"
                  tabIndex={0}
                  aria-label={`Open ${p.title} — ${dollars(p.stake_amount_cents)} on the line`}
                  className="home-card real"
                  style={cardStyle(i)}
                  onClick={() => openCard(p.id)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openCard(p.id); } }}
                >
                  <div className="home-card-top">
                    <div className="home-card-glyph"><Glyph name={goalGlyph(p.title)} /></div>
                    <div className={`home-card-flag ${behind ? "risk" : "ok"}`}>
                      <span className="dot" />{behind ? "At risk" : "On track"}
                    </div>
                  </div>
                  <div className="home-card-name-wrap">
                    <div className="home-card-name">{p.title}</div>
                    <div className="home-card-sub">
                      {cad ? `${cad.days_per_week} days a week` : `${p.target_count}×`}
                    </div>
                  </div>
                  <div className="home-card-row">
                    <div>
                      <div className="home-card-k m">On the line</div>
                      <div className="home-card-stake m">{dollars(p.stake_amount_cents)}</div>
                    </div>
                    <div className="ar">
                      <div className="home-card-k m">Logged</div>
                      <div className="home-card-streak">{prog?.valid_count ?? 0} day{(prog?.valid_count ?? 0) === 1 ? "" : "s"}</div>
                    </div>
                  </div>
                  <div className="home-card-foot">
                    <span className="home-card-script">pact</span>
                    <span className="home-card-no m">No. {pactNo(p.id)}</span>
                  </div>
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
          {pacts === null ? (
            <div className="home-empty">Loading…</div>
          ) : ledger.length === 0 ? (
            <div className="home-empty">Nothing closed yet — your finished pacts will line up here.</div>
          ) : (
            ledger.map((p) => <LedgerRow key={p.id} pact={p} charity={charities[p.charity_id]} onClick={() => navigate(`/pact/${p.id}`)} />)
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

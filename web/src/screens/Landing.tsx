import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import "./landing.css";

// The wishes that cycle through the blue bubble — one per supported goal.
const WISHES = [
  "worked out more",
  "used my phone less",
  "doomscrolled less",
  "meditated more",
  "read more at night",
  "shipped every day",
];

const DECK = [
  { title: "Work out", sub: "Move your body" },
  { title: "Read", sub: "Feed your mind" },
  { title: "No phone at night", sub: "Reclaim your evenings" },
];

export function Landing() {
  const navigate = useNavigate();
  const [revealed, setRevealed] = useState(false);
  const [wi, setWi] = useState(0);

  // One-time: friend's gray bubble is up; "you" type for a beat, then the blue
  // bubble lands and the wish starts cycling.
  useEffect(() => {
    const reveal = setTimeout(() => setRevealed(true), 1500);
    return () => clearTimeout(reveal);
  }, []);

  useEffect(() => {
    if (!revealed) return;
    const id = setInterval(() => setWi((w) => (w + 1) % WISHES.length), 2300);
    return () => clearInterval(id);
  }, [revealed]);

  const scrollToDeck = () =>
    document.getElementById("deck")?.scrollIntoView({ behavior: "smooth" });

  return (
    <div className="landing">
      {/* ── Hero: the iPhone ───────────────────────────────────────────────── */}
      <section className="lp-hero">
        <div className="lp-phone">
          <div className="lp-phone-notch" />
          <div className="lp-screen">
            <div className="lp-imsg-top">
              <span className="lp-imsg-back">‹</span>
              <div className="lp-imsg-contact">
                <div className="lp-imsg-avatar">f</div>
                <div className="lp-imsg-name">friend</div>
              </div>
              <span className="lp-imsg-spacer" />
            </div>

            <div className="lp-thread">
              <div className="lp-bubble lp-in">you've been quiet lately. everything ok?</div>

              {!revealed ? (
                <div className="lp-bubble lp-out lp-typing">
                  <span /> <span /> <span />
                </div>
              ) : (
                <div className="lp-bubble lp-out lp-wish">
                  honestly? i wish i{" "}
                  <span key={wi} className="lp-wishword">
                    {WISHES[wi]}
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>

        <button className="lp-scrollcue" onClick={scrollToDeck} aria-label="Scroll down">
          <span className="lp-scrolltext">so do something about it</span>
          <span className="lp-chevron">⌄</span>
        </button>
      </section>

      {/* ── Deck: what are you committing to? ──────────────────────────────── */}
      <section className="lp-deck" id="deck">
        <div className="lp-deck-eyebrow m">A binding agreement with yourself</div>
        <h1 className="lp-deck-title">What are you committing to?</h1>
        <p className="lp-deck-sub">
          Stake money on it. Your agent coaches you, judges your proof, and if you flake,
          your stake goes to charity. Keep your word — or pay up.
        </p>

        <div className="lp-deck-cards">
          {DECK.map((c) => (
            <button key={c.title} className="lp-card" onClick={() => navigate("/create")}>
              <div className="lp-card-title">{c.title}</div>
              <div className="lp-card-sub">{c.sub}</div>
              <div className="lp-card-foot m">
                <span>pact</span>
                <span>→</span>
              </div>
            </button>
          ))}
        </div>

        <button className="lp-cta" onClick={() => navigate("/create")}>
          Make a pact <span aria-hidden="true">→</span>
        </button>
      </section>
    </div>
  );
}

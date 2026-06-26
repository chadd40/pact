import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, DEMO_OWNER } from "../api";
import { useDemo } from "../App";
import { Reveal } from "../components/Reveal";
import { dollars, formatDate, isTerminal, statusChip, succeeded } from "../lib";
import type { Pact, Profile } from "../types";

export function Home() {
  const { bump, nowMs } = useDemo();
  const navigate = useNavigate();
  const [pacts, setPacts] = useState<Pact[] | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      const [p, prof] = await Promise.all([
        api.listPacts(DEMO_OWNER).catch(() => []),
        api.profile(DEMO_OWNER).catch(() => null),
      ]);
      if (!alive) return;
      // Newest first.
      p.sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at));
      setPacts(p);
      setProfile(prof);
    })();
    return () => {
      alive = false;
    };
  }, [bump]);

  // The profile only aggregates outcomes settled through the API; demo-seeded pacts
  // are settled internally and don't fold in. So derive the headline stats from the
  // settled pacts on the ledger, preferring the richer source.
  const settled = (pacts ?? []).filter((p) => isTerminal(p.status));
  const keptPacts = settled.filter((p) => succeeded(p.status));
  const derivedKept = keptPacts.length;
  const derivedFailed = settled.length - derivedKept;

  const kept = Math.max(profile?.kept ?? 0, derivedKept);
  const failed = Math.max(profile?.failed ?? 0, derivedFailed);
  const total = kept + failed;
  const bestStreak = Math.max(profile?.best_streak ?? 0, derivedKept);
  const currentStreak = Math.max(profile?.current_streak ?? 0, derivedKept);

  return (
    <div className="page">
      <Reveal>
        <Reveal.Item>
          <div className="eyebrow" style={{ marginBottom: 18 }}>
            <span className="mono-label">A binding agreement with yourself</span>
            <span className="rule" />
          </div>
        </Reveal.Item>

        <Reveal.Item>
          <div className="hero-streak">
            <h1 className="streak-headline">
              {total === 0 ? (
                <>
                  No pacts <em>settled</em> yet.
                  <br />
                  Make one binding.
                </>
              ) : (
                <>
                  You've kept <em>{kept}</em> of your last {total}.
                </>
              )}
            </h1>
            <div className="streak-stats">
              <div className="stat">
                <div className="stat-num green">{currentStreak}</div>
                <div className="mono-label">Current streak</div>
              </div>
              <div className="stat">
                <div className="stat-num">{bestStreak}</div>
                <div className="mono-label">Best streak</div>
              </div>
              <div className="stat">
                <div className="stat-num red">{failed}</div>
                <div className="mono-label">Forfeited</div>
              </div>
            </div>
          </div>
        </Reveal.Item>

        <Reveal.Item>
          <div className="section-head" style={{ marginTop: 26 }}>
            <h2 style={{ fontSize: 22 }}>The ledger</h2>
            <button className="btn" onClick={() => navigate("/create")}>
              + New pact
            </button>
          </div>
        </Reveal.Item>

        <Reveal.Item>
          {pacts === null ? (
            <div className="center-note">
              <span className="spin" /> Loading the ledger…
            </div>
          ) : pacts.length === 0 ? (
            <div className="empty">
              <p className="serif-italic" style={{ fontSize: 20, marginBottom: 8 }}>
                The ledger is empty.
              </p>
              <p className="muted" style={{ marginBottom: 18 }}>
                Seed the demo from the console above, or draft your first pact.
              </p>
              <button className="btn" onClick={() => navigate("/create")}>
                Draft a pact
              </button>
            </div>
          ) : (
            <div className="pacts-list">
              {pacts.map((p) => {
                const chip = statusChip(p.status);
                const dest = isTerminal(p.status) ? `/verdict/${p.id}` : `/pact/${p.id}`;
                return (
                  <Link to={dest} className="pact-row" key={p.id}>
                    <div>
                      <div className="pact-row-title">{p.title}</div>
                      <div className="pact-row-meta">
                        <span className="mono-label">
                          {p.target_count}× · distinct days
                        </span>
                        <span className="mono-label">Due {formatDate(p.deadline_at)}</span>
                      </div>
                    </div>
                    <div className="pact-row-right">
                      <span className="pact-stake">{dollars(p.stake_amount_cents)}</span>
                      <span className={`chip ${chip.cls}`}>{chip.label}</span>
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </Reveal.Item>
      </Reveal>

      {/* faint footer motif */}
      <div style={{ marginTop: 60, textAlign: "center" }}>
        <span className="mono-label" style={{ letterSpacing: "0.3em", opacity: 0.5 }}>
          § BINDING AGREEMENT · {nowMs ? new Date(nowMs).getFullYear() : ""} §
        </span>
      </div>
    </div>
  );
}

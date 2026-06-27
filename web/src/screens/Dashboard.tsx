import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, DEMO_OWNER } from "../api";
import { useDemo } from "../App";
import { LinkConnect } from "../components/LinkConnect";
import { ProgressRing } from "../components/ProgressRing";
import { dollars, formatDate, isTerminal, statusChip, succeeded } from "../lib";
import type { Charity, LinkStatus, Pact, Profile } from "../types";

export function Dashboard() {
  const { bump } = useDemo();
  const navigate = useNavigate();
  const [pacts, setPacts] = useState<Pact[] | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [link, setLink] = useState<LinkStatus | null>(null);
  const [charities, setCharities] = useState<Record<string, Charity>>({});

  const refreshLink = useCallback(async () => {
    const s = await api.linkStatus(DEMO_OWNER).catch(() => null);
    setLink(s);
  }, []);

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
      refreshLink();
    })();
    return () => {
      alive = false;
    };
  }, [bump, refreshLink]);

  const all = pacts ?? [];
  const active = all.filter((p) => !isTerminal(p.status));
  const settled = all.filter((p) => isTerminal(p.status));

  // Track record: prefer the profile, fall back to the settled ledger (demo pacts
  // are settled internally and don't always fold into the profile).
  const derivedKept = settled.filter((p) => succeeded(p.status)).length;
  const kept = Math.max(profile?.kept ?? 0, derivedKept);
  const failed = Math.max(profile?.failed ?? 0, settled.length - derivedKept);
  const currentStreak = Math.max(profile?.current_streak ?? 0, derivedKept);
  const bestStreak = Math.max(profile?.best_streak ?? 0, derivedKept);

  const showLinkBanner = all.length > 0 && link != null && !link.connected;

  return (
    <div className="dash">
      <div className="dash-eyebrow m">Your pacts</div>

      <div className="dash-record">
        <div className="dash-stat">
          <div className="dash-stat-num green">{currentStreak}</div>
          <div className="dash-stat-label m">Current streak</div>
        </div>
        <div className="dash-stat">
          <div className="dash-stat-num">{bestStreak}</div>
          <div className="dash-stat-label m">Best streak</div>
        </div>
        <div className="dash-stat">
          <div className="dash-stat-num">{kept}</div>
          <div className="dash-stat-label m">Kept</div>
        </div>
        <div className="dash-stat">
          <div className="dash-stat-num red">{failed}</div>
          <div className="dash-stat-label m">Forfeited</div>
        </div>
      </div>

      {showLinkBanner && (
        <LinkConnect owner={DEMO_OWNER} onConnected={refreshLink} variant="banner" />
      )}

      <div className="dash-section-head">
        <h2>Active</h2>
        <button className="pc-btn" onClick={() => navigate("/create")}>
          + New pact
        </button>
      </div>

      {pacts === null ? (
        <div className="dash-note">Loading…</div>
      ) : active.length === 0 ? (
        <div className="dash-empty">
          <div className="dash-empty-title">No active pacts.</div>
          <div className="dash-empty-sub">Make one binding.</div>
          <button className="pc-btn" onClick={() => navigate("/create")}>
            Make your first pact
          </button>
        </div>
      ) : (
        <div className="dash-cards">
          {active.map((p) => (
            <PactCard key={p.id} pact={p} charity={charities[p.charity_id]} />
          ))}
        </div>
      )}

      {settled.length > 0 && (
        <>
          <div className="dash-section-head">
            <h2>History</h2>
          </div>
          <div className="dash-history">
            {settled.map((p) => {
              const chip = statusChip(p.status);
              return (
                <Link to={`/pact/${p.id}`} className="dash-hist-row" key={p.id}>
                  <span className="dash-hist-title">{p.title}</span>
                  <span className="dash-hist-right">
                    <span className="dash-hist-stake m">{dollars(p.stake_amount_cents)}</span>
                    <span className={`chip ${chip.cls}`}>{chip.label}</span>
                  </span>
                </Link>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

function PactCard({ pact, charity }: { pact: Pact; charity?: Charity }) {
  const prog = pact.progress;
  const pct = prog?.pct ?? 0;
  const valid = prog?.valid_count ?? 0;
  const target = prog?.target ?? pact.target_count;
  const daysLeft = prog?.days_left ?? 0;
  const behind = prog?.behind ?? false;
  return (
    <Link to={`/pact/${pact.id}`} className="dash-card">
      <div className="dash-card-top">
        {charity && <img className="dash-card-stamp" src={charity.stamp} alt={charity.name} />}
        <div className="dash-card-headings">
          <div className="dash-card-title">{pact.title}</div>
          <div className="dash-card-meta m">
            {dollars(pact.stake_amount_cents)} · due {formatDate(pact.deadline_at)}
          </div>
        </div>
      </div>
      <div className="dash-card-body">
        <ProgressRing
          pct={pct}
          size={92}
          stroke={8}
          tone={behind ? "muted" : "gold"}
          label={`${valid}/${target}`}
          sub="done"
        />
        <div className="dash-card-side">
          <div className={`dash-pace ${behind ? "behind" : "ontrack"}`}>
            {behind ? "Behind pace" : "On track"}
          </div>
          <div className="dash-days m">
            {daysLeft === 0 ? "Due now" : `${daysLeft} day${daysLeft === 1 ? "" : "s"} left`}
          </div>
        </div>
      </div>
    </Link>
  );
}

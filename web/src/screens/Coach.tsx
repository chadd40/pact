import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, DEMO_OWNER } from "../api";
import { useDemo } from "../App";
import { useAppData } from "../data";
import { GoalGlyph } from "../components/GoalGlyph";
import { formatDateTime } from "../lib";
import type { CoachingMessage } from "../types";

// Global coach view: your agent + the recent nudges across all your pacts.
export function Coach() {
  const { bump } = useDemo();
  const { pacts } = useAppData();
  const navigate = useNavigate();
  const [feed, setFeed] = useState<CoachingMessage[]>([]);

  // Pacts come from shared AppData; only the outbox feed is Coach-specific.
  useEffect(() => {
    let alive = true;
    api.outbox(DEMO_OWNER)
      .then((out) => alive && setFeed(out.slice().reverse()))
      .catch(() => {});
    return () => { alive = false; };
  }, [bump]);

  const byId = Object.fromEntries(pacts.map((p) => [p.id, p]));
  const coached = pacts.filter((p) => p.status === "active" || p.status === "evaluating" || p.status === "needs_review");

  return (
    <div className="pg">
      <div className="pg-head">
        <div className="pg-eyebrow m">Your agent</div>
        <div className="pg-title">Coach</div>
        <div className="pg-lede">Hermes is watching every live pact — nudging you toward your stake and judging your proof. Open any pact to talk.</div>
      </div>

      <div className="coach-hero">
        <div className="coach-hero-av"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" width="26" height="26"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8Z" /></svg></div>
        <div className="coach-hero-body">
          <div className="coach-hero-name">Hermes</div>
          <div className="coach-hero-sub"><span className="dot" />Connected · coaching {coached.length} pact{coached.length === 1 ? "" : "s"}</div>
        </div>
      </div>

      <div className="pg-section-label m">Recent from your coach</div>
      {feed.length === 0 ? (
        <div className="pg-empty">No nudges waiting. You're all caught up.</div>
      ) : (
        <div className="coach-feed">
          {feed.map((m) => {
            const p = byId[m.pact_id];
            return (
              <button key={m.id} className="coach-feed-row" onClick={() => navigate(`/pact/${m.pact_id}`)}>
                <span className="coach-feed-glyph">{p ? <GoalGlyph title={p.title} size={18} /> : null}</span>
                <span className="coach-feed-main">
                  <span className="coach-feed-pact">{p?.title ?? "Pact"}</span>
                  <span className="coach-feed-body">{m.body}</span>
                </span>
                <span className="coach-feed-when m">{formatDateTime(m.sent_at)}</span>
              </button>
            );
          })}
        </div>
      )}

      <div className="pg-section-label m">Live pacts</div>
      {coached.length === 0 ? (
        <div className="pg-empty">No live pacts right now.</div>
      ) : (
        <div className="coach-pacts">
          {coached.map((p) => (
            <button key={p.id} className="coach-pact-row" onClick={() => navigate(`/pact/${p.id}`)}>
              <span className="coach-pact-glyph"><GoalGlyph title={p.title} size={18} /></span>
              <span className="coach-pact-name">{p.title}</span>
              <span className="coach-pact-open">Open chat
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><path d="M9 6l6 6-6 6" /></svg>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

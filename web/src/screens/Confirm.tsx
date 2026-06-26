import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, DEMO_OWNER } from "../api";
import { useDemo } from "../App";
import { Reveal } from "../components/Reveal";
import { dollars, formatDate } from "../lib";
import type { Charity, Pact } from "../types";

export function Confirm() {
  const { pactId } = useParams();
  const navigate = useNavigate();
  const { signalChange } = useDemo();
  const [pact, setPact] = useState<Pact | null>(null);
  const [charities, setCharities] = useState<Charity[]>([]);
  const [stakeDollars, setStakeDollars] = useState<string>("");
  const [charityId, setCharityId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      const [p, cs] = await Promise.all([api.getPact(pactId!), api.charities()]);
      if (!alive) return;
      setPact(p);
      setCharities(cs);
      setStakeDollars((p.recommended_stake_cents / 100).toFixed(0));
      setCharityId(p.charity_id || cs[0]?.id || "");
    })();
    return () => {
      alive = false;
    };
  }, [pactId]);

  if (!pact) {
    return (
      <div className="page">
        <div className="center-note">
          <span className="spin" /> Drawing up the contract…
        </div>
      </div>
    );
  }

  const stakeCents = Math.round((parseFloat(stakeDollars) || 0) * 100);
  const r = pact.rubric;

  const sign = async () => {
    setBusy(true);
    setErr(null);
    try {
      // Stamp the owner first so the profile aggregates this pact.
      await api.setOwner(pact.id, DEMO_OWNER).catch(() => {});
      await api.confirmPact(pact.id, stakeCents, charityId);
      signalChange();
      navigate(`/pact/${pact.id}`);
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Could not start the pact.");
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <Link to="/create" className="backlink">
        ← Redraft
      </Link>

      <Reveal>
        <Reveal.Item>
          <div className="doc contract">
            <div className="contract-head">
              <span className="mono-label" style={{ letterSpacing: "0.3em" }}>
                § BINDING AGREEMENT §
              </span>
              <h1 className="contract-title">{pact.title}</h1>
              <p className="serif-italic muted">{pact.goal}</p>
            </div>

            <Clause label="Original intent">
              <span className="muted">"{pact.original_prompt}"</span>
            </Clause>

            <Clause label="The terms">
              <span className="clause-val big">
                {pact.target_count}× across distinct days
              </span>
              <div className="mono-label" style={{ marginTop: 6 }}>
                Minimum {r.min_distinct_days} distinct days · {pact.freezes_allowed} freeze
                allowed
              </div>
            </Clause>

            <Clause label="Deadline">
              <span className="clause-val big data">{formatDate(pact.deadline_at)}</span>
              <div className="mono-label" style={{ marginTop: 6 }}>
                {pact.timezone}
              </div>
            </Clause>

            <Clause label="Frozen rubric">
              <div>
                <div className="mono-label" style={{ marginBottom: 6 }}>
                  Proof: {r.modality} · token required
                </div>
                <strong style={{ fontSize: 13 }}>Must show</strong>
                <ul className="must-show" style={{ margin: "4px 0 12px", paddingLeft: 18 }}>
                  {r.must_show.map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
                <strong style={{ fontSize: 13 }}>Auto-rejected</strong>
                <ul className="reject" style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                  {r.reject_if.map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
              </div>
            </Clause>

            <Clause label="The stake">
              <div className="stake-editor">
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 22, fontWeight: 600 }}>
                  $
                </span>
                <input
                  className="stake-input"
                  type="number"
                  min={5}
                  max={500}
                  value={stakeDollars}
                  onChange={(e) => setStakeDollars(e.target.value)}
                />
                <span className="recommended-tag">
                  agent recommends {dollars(pact.recommended_stake_cents)}
                </span>
              </div>
              <div className="mono-label" style={{ marginTop: 8 }}>
                If you fail, this moves to the charity below. If you keep it, $0 moves.
              </div>
            </Clause>

            <Clause label="Beneficiary">
              <div className="charity-grid">
                {charities.map((c) => (
                  <button
                    key={c.id}
                    className={`charity-opt ${charityId === c.id ? "selected" : ""}`}
                    onClick={() => setCharityId(c.id)}
                  >
                    <div className="charity-name">{c.name}</div>
                    <div className="charity-cat">{c.category.replace(/_/g, " ")}</div>
                  </button>
                ))}
              </div>
            </Clause>

            <p className="honesty-line">
              I understand this is an honesty-based commitment. Server time is the source of
              truth; duplicate or fabricated proof voids the pact. By signing I authorize the
              stake to move to my chosen charity if I do not keep my word.
            </p>

            {err && (
              <div className="refusal" style={{ marginTop: 14 }}>
                <span>✕</span>
                <div>{err}</div>
              </div>
            )}

            <div className="sign-row">
              <Link to="/" className="btn btn-ghost">
                Tear up
              </Link>
              <button
                className="btn btn-seal"
                onClick={sign}
                disabled={busy || stakeCents <= 0 || !charityId}
              >
                {busy ? <span className="spin" /> : "✶"} Approve stake & start
              </button>
            </div>
          </div>
        </Reveal.Item>
      </Reveal>
    </div>
  );
}

function Clause({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="clause">
      <div className="clause-key mono-label">{label}</div>
      <div className="clause-val">{children}</div>
    </div>
  );
}

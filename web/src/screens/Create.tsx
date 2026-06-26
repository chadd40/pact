import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api";
import { Reveal } from "../components/Reveal";

const EXAMPLES = [
  "Work out 5 times this week or $20 to charity",
  "Ship the landing page by Friday or stake $25",
  "Read 30 pages a day for 5 days or forfeit $15",
  "Practice Spanish 6 days this week or $20 moves",
];

export function Create() {
  const navigate = useNavigate();
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);

  const generate = async () => {
    if (!prompt.trim()) return;
    setBusy(true);
    setRefusal(null);
    try {
      const pact = await api.draftPact(prompt.trim());
      navigate(`/confirm/${pact.id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        // Safety gate refused this goal — render the coach's reason gracefully.
        setRefusal(e.detail);
      } else {
        setRefusal("Something went wrong drafting that pact. Try rephrasing your commitment.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <Link to="/" className="backlink">
        ← The ledger
      </Link>

      <Reveal>
        <Reveal.Item>
          <div className="eyebrow" style={{ marginBottom: 16 }}>
            <span className="mono-label">Draft · clause 01</span>
            <span className="rule" />
          </div>
        </Reveal.Item>

        <Reveal.Item>
          <h1 style={{ fontSize: "clamp(32px,5vw,52px)", marginBottom: 10 }}>
            What will you do,
            <br />
            <span className="serif-italic" style={{ color: "var(--sealed-gold)" }}>
              by when, what's at stake?
            </span>
          </h1>
        </Reveal.Item>

        <Reveal.Item>
          <p className="muted" style={{ maxWidth: 580, marginBottom: 24 }}>
            State it plainly. The agent will draft a binding contract — a frozen rubric,
            a proof rule, and a recommended stake you'll review before signing.
          </p>
        </Reveal.Item>

        <Reveal.Item>
          <textarea
            className="create-prompt"
            placeholder="e.g. Work out 5 times this week, or $20 goes to charity…"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) generate();
            }}
          />
          <div className="chips">
            {EXAMPLES.map((ex) => (
              <button key={ex} className="example-chip" onClick={() => setPrompt(ex)}>
                {ex}
              </button>
            ))}
          </div>
        </Reveal.Item>

        {refusal && (
          <Reveal.Item>
            <div className="refusal">
              <span style={{ fontSize: 18, lineHeight: 1 }}>✕</span>
              <div>
                <div className="mono-label" style={{ color: "var(--stake-red)", marginBottom: 4 }}>
                  Refused — won't bind this goal
                </div>
                <div>{refusal}</div>
              </div>
            </div>
          </Reveal.Item>
        )}

        <Reveal.Item>
          <div style={{ marginTop: 26, display: "flex", gap: 14, alignItems: "center" }}>
            <button className="btn" onClick={generate} disabled={busy || !prompt.trim()}>
              {busy ? <span className="spin" /> : null}
              Generate pact
            </button>
            <span className="mono-label">⌘ + Enter</span>
          </div>
        </Reveal.Item>
      </Reveal>
    </div>
  );
}

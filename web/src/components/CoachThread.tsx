import { useState } from "react";
import type { CoachingMessage } from "../types";

// The coaching conversation: the agent's handoff + nudges (outbound) interleaved
// with the user's check-ins (inbound), plus a composer to message the agent.
interface Props {
  messages: CoachingMessage[];
  onSend: (text: string) => Promise<void> | void;
  agentName?: string;
}

export function CoachThread({ messages, onSend, agentName = "Hermes" }: Props) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  const send = async () => {
    const text = draft.trim();
    if (!text || busy) return;
    setBusy(true);
    try {
      await onSend(text);
      setDraft("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="coach">
      <div className="coach-list">
        {messages.length === 0 && <div className="coach-empty">No messages yet.</div>}
        {messages.map((m) => (
          <div key={m.id} className={`coach-msg coach-${m.direction}`}>
            {m.direction === "outbound" && <div className="coach-who">{agentName}</div>}
            <div className="coach-bubble">{m.body}</div>
          </div>
        ))}
      </div>
      <div className="coach-compose">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") send();
          }}
          placeholder={`Message ${agentName}…`}
          aria-label="Message your agent"
        />
        <button className="pc-btn" onClick={send} disabled={busy || !draft.trim()}>
          {busy ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}

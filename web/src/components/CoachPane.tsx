import { useEffect, useRef, useState } from "react";
import type { CoachingMessage, Pact } from "../types";

// Slide-in coaching pane: the agent's nudges + the user's check-ins, with a composer.
export function CoachPane({
  pact,
  messages,
  onSend,
  onClose,
}: {
  pact: Pact;
  messages: CoachingMessage[];
  onSend: (text: string) => Promise<void> | void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const agent = pact.agent ?? "Hermes";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages]);

  const send = async () => {
    const t = draft.trim();
    if (!t || busy) return;
    setBusy(true);
    try { await onSend(t); setDraft(""); } finally { setBusy(false); }
  };

  return (
    <div className="ov" role="dialog" aria-modal="true">
      <div className="ov-backdrop" onClick={onClose} />
      <div className="ov-pane">
        <div className="cp-head">
          <div className="cp-head-left">
            <div className="cp-av"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width="20" height="20"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8Z" /></svg></div>
            <div>
              <div className="cp-name">{agent}</div>
              <div className="cp-status"><span className="dot" />Coaching this pact</div>
            </div>
          </div>
          <button className="ov-x" onClick={onClose} aria-label="Close"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" width="15" height="15"><path d="M6 6l12 12M18 6 6 18" /></svg></button>
        </div>
        <div className="cp-thread" ref={listRef}>
          {messages.length === 0 && <div className="cp-empty m">No messages yet — say hi to {agent}.</div>}
          {messages.map((m) => (
            <div key={m.id} className={`cp-msg ${m.direction === "outbound" ? "them" : "you"}`}>
              {m.body}
            </div>
          ))}
        </div>
        <div className="cp-compose">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") send(); }}
            placeholder={`Message ${agent}…`}
            aria-label={`Message ${agent}`}
          />
          <button className="cp-send" onClick={send} disabled={busy || !draft.trim()} aria-label="Send">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="17" height="17"><path d="M5 12h13M12 6l6 6-6 6" /></svg>
          </button>
        </div>
      </div>
    </div>
  );
}

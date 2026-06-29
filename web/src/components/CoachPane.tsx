import { useEffect, useRef, useState } from "react";
import { AgentAvatar, ChatShell, type ChatMessage } from "./ChatShell";
import { AGENTS } from "../screens/Create";
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
  const [attachments, setAttachments] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const agent = pact.agent ?? "Hermes";
  const agentDef = AGENTS.find((a) => a.key === pact.agent) ?? AGENTS[0];

  useEffect(() => { inputRef.current?.focus(); }, []);

  const send = async () => {
    const t = draft.trim();
    if (!t || busy) return;
    setBusy(true);
    try { await onSend(t); setDraft(""); setAttachments([]); } finally { setBusy(false); }
  };

  const onAttachmentChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (!files.length) return;
    setAttachments((current) => [...current, ...files.map((file) => file.name)]);
  };

  const rows: ChatMessage[] = messages.length
    ? messages.map((m) => ({
      id: m.id,
      role: m.direction === "outbound" ? "agent" : "user",
      body: m.body,
    }))
    : [{
      id: "empty",
      role: "agent",
      body: `I'm here when you want to tune the plan, check proof, or make the next rep easier.`,
    }];

  return (
    <div className="ov" role="dialog" aria-modal="true" aria-label={`Chat with ${agent}`}>
      <div className="ov-backdrop" onClick={onClose} />
      <div className="ov-pane ov-pane-chat" tabIndex={-1}>
        <div className="cp-head">
          <div className="cp-head-left">
            <AgentAvatar src={agentDef.avatar} name={agent} />
            <div className="cp-name">{agent}</div>
          </div>
          <button className="ov-x" onClick={onClose} aria-label="Close"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" width="15" height="15"><path d="M6 6l12 12M18 6 6 18" /></svg></button>
        </div>
        <ChatShell
          label={`${agent} pact chat`}
          agentName={agent}
          agentAvatar={agentDef.avatar}
          messages={rows}
          showHeader={false}
          composer={(
            <div className="cp-compose-wrap">
              {attachments.length > 0 && (
                <div className="cp-attachments" aria-label="Selected attachments">
                  {attachments.map((name, index) => (
                    <span className="cp-attachment" key={`${name}-${index}`}>{name}</span>
                  ))}
                </div>
              )}
              <div className="cp-compose">
                <button className="cp-add" aria-label="Add photos or files" type="button" onClick={() => fileRef.current?.click()}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" width="17" height="17"><path d="M12 5v14M5 12h14" /></svg>
                </button>
                <input
                  ref={fileRef}
                  type="file"
                  multiple
                  hidden
                  accept="image/*,.pdf,.txt,.md,.csv,.json"
                  onChange={onAttachmentChange}
                />
                <input
                  ref={inputRef}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") send(); }}
                  placeholder={`Message ${agent}...`}
                  aria-label={`Message ${agent}`}
                />
                <button className="cp-send" onClick={send} disabled={busy || !draft.trim()} aria-label="Send">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="17" height="17"><path d="M5 12h13M12 6l6 6-6 6" /></svg>
                </button>
              </div>
            </div>
          )}
        />
      </div>
    </div>
  );
}

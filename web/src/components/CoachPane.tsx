import { useEffect, useRef, useState } from "react";
import { AgentAvatar, ChatShell, type ChatMessage } from "./ChatShell";
import { useFocusTrap } from "./useFocusTrap";
import { AGENTS } from "../screens/Create";
import type { CoachingMessage, Pact } from "../types";

// Slide-in coaching pane: the agent's nudges + the user's check-ins, with a composer.
export function CoachPane({
  pact,
  messages,
  agentServing = true,
  onSend,
  onClose,
}: {
  pact: Pact;
  messages: CoachingMessage[];
  // Whether the owner's agent is actually connected (running `pact serve`). When
  // false, replies come from Pact's local fallback, and we say so rather than
  // pass the fallback off as the agent.
  agentServing?: boolean;
  onSend: (text: string, attachments?: File[]) => Promise<void> | void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [attachments, setAttachments] = useState<File[]>([]);
  const paneRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const agent = pact.agent ?? "Hermes";
  const agentDef = AGENTS.find((a) => a.key === pact.agent) ?? AGENTS[0];
  const canSend = draft.trim().length > 0 || attachments.length > 0;

  // Trap focus + Escape-to-close + focus-restore, like the other modals (a11y).
  useFocusTrap(paneRef, onClose);
  // Prefer the composer over the trap's default first-focusable (the close button).
  useEffect(() => { inputRef.current?.focus(); }, []);

  const send = async () => {
    const t = draft.trim();
    if (!canSend || busy) return;
    setBusy(true);
    try { await onSend(t, attachments); setDraft(""); setAttachments([]); } finally { setBusy(false); }
  };

  const onAttachmentChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (!files.length) return;
    setAttachments((current) => [...current, ...files]);
  };
  const removeAttachment = (index: number) => {
    setAttachments((current) => current.filter((_, i) => i !== index));
  };

  const rows: ChatMessage[] = messages.length
    ? messages.map((m) => ({
      id: m.id,
      role: m.direction === "outbound" ? "agent" : "user",
      body: (
        <>
          <span>{m.body}</span>
          {!!m.attachments?.length && (
            <div className="cp-message-attachments">
              {m.attachments.map((attachment, index) => (
                <span key={`${attachment.filename}-${index}`}>{attachment.filename}</span>
              ))}
            </div>
          )}
        </>
      ),
    }))
    : [{
      id: "empty",
      role: "agent",
      body: `I'm here when you want to tune the plan, check proof, or make the next rep easier.`,
    }];

  return (
    <div className="ov" role="dialog" aria-modal="true" aria-label={`Chat with ${agent}`}>
      <div className="ov-backdrop" onClick={onClose} />
      <div className="ov-pane ov-pane-chat" tabIndex={-1} ref={paneRef}>
        <div className="cp-head">
          <div className="cp-head-left">
            <AgentAvatar src={agentDef.avatar} name={agent} />
            <div className="cp-name">{agent}</div>
          </div>
          <button className="ov-x" onClick={onClose} aria-label="Close"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" width="15" height="15"><path d="M6 6l12 12M18 6 6 18" /></svg></button>
        </div>
        {!agentServing && (
          <div className="cp-offline" role="status">
            {agent} isn't connected right now, so these replies are Pact's local fallback — not your agent. Run <code>pact serve</code> (Settings → Agent) to coach with {agent}.
          </div>
        )}
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
                  {attachments.map((file, index) => (
                    <span className="cp-attachment" key={`${file.name}-${index}`}>
                      <span>{file.name}</span>
                      <button
                        type="button"
                        className="cp-attachment-remove"
                        aria-label={`Remove ${file.name}`}
                        onClick={() => removeAttachment(index)}
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" width="11" height="11"><path d="M6 6l12 12M18 6 6 18" /></svg>
                      </button>
                    </span>
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
                  className="file-input-offscreen"
                  tabIndex={-1}
                  aria-hidden="true"
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
                <button className="cp-send" onClick={send} disabled={busy || !canSend} aria-label="Send">
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

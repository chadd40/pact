import type { ReactNode } from "react";

export interface ChatMessage {
  id: string;
  role: "agent" | "user" | "system";
  body: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
}

export function AgentAvatar({
  src,
  name,
  size = "md",
}: {
  src?: string | null;
  name: string;
  size?: "sm" | "md" | "lg";
}) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("") || "P";
  return (
    <span className={`chat-avatar ${size}`} aria-hidden="true">
      {src ? <img src={src} alt="" /> : <span>{initials}</span>}
    </span>
  );
}

export function StatusDot({ tone }: { tone: "ok" | "warn" | "muted" | "busy" }) {
  return <span className={`status-dot ${tone}`} aria-hidden="true" />;
}

export function StatusPill({
  tone,
  children,
}: {
  tone: "ok" | "warn" | "muted" | "busy";
  children: ReactNode;
}) {
  return (
    <span className={`status-pill ${tone}`}>
      <StatusDot tone={tone} />
      {children}
    </span>
  );
}

export function ChatShell({
  label,
  agentName,
  agentAvatar,
  messages,
  composer,
  showHeader = true,
}: {
  label: string;
  agentName: string;
  agentAvatar?: string | null;
  messages: ChatMessage[];
  composer?: ReactNode;
  showHeader?: boolean;
}) {
  return (
    <div className="chat-shell">
      {showHeader && (
        <div className="chat-shell-head">
          <AgentAvatar src={agentAvatar} name={agentName} />
          <div className="chat-shell-title">{agentName}</div>
        </div>
      )}
      <div className="chat-log" role="log" aria-label={label}>
        {messages.map((message) => (
          <div key={message.id} className={`chat-row ${message.role}`}>
            {message.role === "agent" && <AgentAvatar src={agentAvatar} name={agentName} size="sm" />}
            <div className="chat-bubble-wrap">
              {message.meta && <div className="chat-meta m">{message.meta}</div>}
              <div className="chat-bubble">{message.body}</div>
              {message.actions && <div className="chat-actions">{message.actions}</div>}
            </div>
          </div>
        ))}
      </div>
      {composer}
    </div>
  );
}

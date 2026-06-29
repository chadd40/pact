// web/src/components/PasteWebPact.tsx
import { useState } from "react";
import { decodeDraft, type PactDraft } from "../lib/handoff";
import "./paste-web-pact.css";

export function PasteWebPact({ onImport }: { onImport: (draft: PactDraft) => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (!open) {
    return (
      <button type="button" className="pwp-chip" aria-label="Paste web pact" onClick={() => setOpen(true)}>
        <span className="pwp-chip-orbit" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="17" height="17">
            <path d="M8 7h8M8 11h8M8 15h5" />
            <rect x="5" y="3" width="14" height="18" rx="2" />
          </svg>
        </span>
        <span className="pwp-chip-copy">
          <span className="pwp-chip-kicker">From pact.com</span>
          <span className="pwp-chip-title">Paste web pact</span>
        </span>
        <span className="pwp-chip-status" aria-hidden="true">
          <span className="pwp-status-dot" />
          Clipboard
        </span>
      </button>
    );
  }

  const submit = () => {
    const r = decodeDraft(text);
    if (!r.ok) { setError(r.error); return; }
    setError(null);
    onImport(r.draft);
  };

  return (
    <div className="pwp-panel">
      <div className="pwp-panel-head">
        <span className="pwp-chip-orbit sm" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="15" height="15">
            <path d="M8 7h8M8 11h8M8 15h5" />
            <rect x="5" y="3" width="14" height="18" rx="2" />
          </svg>
        </span>
        <div>
          <div className="pwp-panel-kicker">Clipboard handoff</div>
          <label className="pwp-panel-title" htmlFor="pwp-input">Paste web pact</label>
        </div>
      </div>
      <textarea
        id="pwp-input"
        className="pwp-input"
        aria-label="Paste your pact from the web"
        placeholder="Paste your pact link here…"
        value={text}
        autoFocus
        onChange={(e) => { setText(e.target.value); setError(null); }}
      />
      {text.trim() && (
        <button type="button" className="pwp-submit" aria-label="Submit pasted pact" onClick={submit}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" width="16" height="16" aria-hidden="true">
            <path d="M5 12h13M12 6l6 6-6 6" />
          </svg>
          <span>Import</span>
        </button>
      )}
      {error && <div role="alert" className="pwp-error">{error}</div>}
    </div>
  );
}

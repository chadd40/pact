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
      <button type="button" className="pwp-chip" onClick={() => setOpen(true)}>
        paste web pact here
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
      <textarea
        className="pwp-input"
        aria-label="Paste your pact from the web"
        placeholder="Paste your pact link here…"
        value={text}
        autoFocus
        onChange={(e) => { setText(e.target.value); setError(null); }}
      />
      {text.trim() && (
        <button type="button" className="pwp-submit" aria-label="Submit pasted pact" onClick={submit}>
          ✓
        </button>
      )}
      {error && <div role="alert" className="pwp-error">{error}</div>}
    </div>
  );
}

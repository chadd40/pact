// web/src/components/PasteWebPact.tsx
import { useEffect, useRef, useState } from "react";
import { decodeDraft, type PactDraft } from "../lib/handoff";
import "./paste-web-pact.css";

// The desktop paste-import affordance: a 50px circle that sits left of "Choose
// this card". Clicking reads the clipboard, validates the web pact blob, and
// morphs into a status pill that spans the control group — green "Pact imported"
// on success, an inline error (auto-collapsing back to the circle) on failure.
// Spec: docs/superpowers/specs/2026-06-29-paste-import-and-agent-setup-design.md.

type State =
  | { kind: "idle" }
  | { kind: "busy"; label: string }
  | { kind: "ok" }
  | { kind: "err"; message: string };

function ClipboardIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" width="20" height="20" aria-hidden="true">
      <rect x="8" y="3" width="8" height="4" rx="1.2" />
      <path d="M9 5H6.5A1.5 1.5 0 0 0 5 6.5v12A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5v-12A1.5 1.5 0 0 0 17.5 5H15" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" width="18" height="18" aria-hidden="true">
      <path d="M5 12.5l4.5 4.5L19 7" />
    </svg>
  );
}

export function PasteWebPact({ onImport }: { onImport: (draft: PactDraft) => void }) {
  const [state, setState] = useState<State>({ kind: "idle" });
  const collapse = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (collapse.current) clearTimeout(collapse.current);
    },
    []
  );

  const failBack = (message: string) => {
    setState({ kind: "err", message });
    if (collapse.current) clearTimeout(collapse.current);
    // Show the error briefly, then collapse back to the circle so the user can retry.
    collapse.current = setTimeout(() => setState({ kind: "idle" }), 2800);
  };

  const run = async () => {
    if (state.kind === "busy" || state.kind === "ok") return;
    if (collapse.current) {
      clearTimeout(collapse.current);
      collapse.current = null;
    }
    setState({ kind: "busy", label: "Reading clipboard" });
    let text: string;
    try {
      text = await navigator.clipboard.readText();
    } catch {
      failBack("Couldn't read the clipboard. Copy your pact from the web, then try again.");
      return;
    }
    setState({ kind: "busy", label: "Checking pact" });
    const result = decodeDraft(text);
    if (!result.ok) {
      failBack(result.error || "That clipboard text isn't a Pact link.");
      return;
    }
    setState({ kind: "ok" });
    onImport(result.draft);
  };

  return (
    <>
      <button
        type="button"
        className="pwp-circle"
        aria-label="Paste web pact"
        onClick={run}
        disabled={state.kind === "busy" || state.kind === "ok"}
      >
        <ClipboardIcon />
        <span className="pwp-tip" aria-hidden="true">
          Paste web pact
        </span>
      </button>

      {state.kind !== "idle" && (
        <div
          className={`pwp-pill pwp-pill-${state.kind}`}
          role={state.kind === "err" ? "alert" : "status"}
          aria-live="polite"
          onClick={state.kind === "err" ? run : undefined}
        >
          {state.kind === "ok" ? (
            <>
              <CheckIcon />
              <span>Pact imported</span>
            </>
          ) : state.kind === "err" ? (
            <span className="pwp-pill-text">{state.message}</span>
          ) : (
            <>
              <span className="pwp-spin" aria-hidden="true" />
              <span>{state.label}</span>
            </>
          )}
        </div>
      )}
    </>
  );
}

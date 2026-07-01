// Small line glyphs shared by the Onboard and Settings agent-connect sections.
// Kept presentational and dependency-free so both screens render an identical
// generate-token / re-check toolbar.

// A horizontal key glyph (bow left, shaft right, teeth down) for the
// generate-token square — reads unmistakably as a credential at small sizes.
export function TokenIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="6.6" cy="12" r="3.3" />
      <path d="M9.9 12 H20" />
      <path d="M16.4 12 V15.5" />
      <path d="M19.4 12 V14.6" />
    </svg>
  );
}

// A circular rewind / re-check arrow.
export function RewindIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M20 12a8 8 0 1 1-2.34-5.66" />
      <path d="M20 4v4h-4" />
    </svg>
  );
}

// Shared goal glyph — maps a pact title to one of the card icons (mirrors the mockup).
export function goalGlyphName(title: string): string {
  const t = title.toLowerCase();
  if (/work\s?out|gym|run|exercise|lift|train|10k|cardio|yoga/.test(t)) return "dumbbell";
  if (/read|book|study|write|sketch|journal/.test(t)) return "book";
  if (/phone|screen|scroll|sleep|night|bed|wake|6am/.test(t)) return "moon";
  if (/meditat|breath|calm|quiet|plunge|cold/.test(t)) return "lotus";
  return "star";
}

export function GoalGlyph({ title, size = 24 }: { title: string; size?: number }) {
  const p = {
    dumbbell: <path d="M3 9v6M6 7.5v9M18 7.5v9M21 9v6M6 12h12" />,
    book: <><path d="M5 4a1 1 0 0 1 1-1h12v16H6a1 1 0 0 0-1 1Z" /><path d="M18 3v16" /></>,
    moon: <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z" />,
    lotus: <path d="M5 19c8 1 14-5 14-14 0 0-13-1-13 8a6 6 0 0 0 2 6Z" />,
    star: <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8Z" />,
  }[goalGlyphName(title)];
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width={size} height={size}>{p}</svg>
  );
}

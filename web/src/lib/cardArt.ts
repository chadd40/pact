import type { Pact } from "../types";
import { asset } from "./asset";

export type CardArt =
  | { kind: "photo"; src: string; title: string }
  | { kind: "art"; src: string }
  | { kind: "glyph"; title: string };

// Map a title to one of the illustrated template cards by keyword. Word-boundary
// matched (so "Spread the word" doesn't trip "read"), first hit wins. Each entry's
// synonyms cover the descriptive titles we use ("Work out 5x this week", "Run 3x")
// plus common variants, so most goals land on a real card instead of a glyph.
const TEMPLATE_KEYWORDS: ReadonlyArray<readonly [RegExp, string]> = [
  [/\b(work\s?out|workout|gym|lift|run|running|ran|jog|cardio|10k|5k|plunge|train(?:ing)?|strength)\b/, "/cards/workout.svg"],
  [/\b(read|reading|book|pages)\b/, "/cards/read.svg"],
  [/\b(ship|shipping|write|writing|wrote|words|sketch|draw(?:ing)?|build|code|coding|inbox|publish|design|blog|journal)\b/, "/cards/ship.svg"],
  [/\b(meditate|meditation|breathe|mindful|yoga|stretch|wake|morning)\b/, "/cards/meditate.svg"],
  [/\b(no\s?phone|phone|screen|scroll|sugar|alcohol|caffeine|soda|junk)\b/, "/cards/nophone.svg"],
];

export function cardArtFor(pact: Pick<Pact, "title" | "card_art">): CardArt {
  // Resolve against the Vite base so the returned `src` works under a subpath
  // (GitHub Pages) as well as at root (dev / Tauri). Wrapped here exactly once —
  // every consumer reads `.src` directly, none re-prefix.
  if (pact.card_art) return { kind: "photo", src: asset(pact.card_art), title: pact.title };
  const t = pact.title.trim().toLowerCase();
  for (const [re, src] of TEMPLATE_KEYWORDS) if (re.test(t)) return { kind: "art", src: asset(src) };
  return { kind: "glyph", title: pact.title };
}

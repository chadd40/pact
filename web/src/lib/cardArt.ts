import type { Pact } from "../types";
import { asset } from "./asset";

export type CardArt =
  | { kind: "photo"; src: string; title: string }
  | { kind: "art"; src: string }
  | { kind: "glyph"; title: string };

const TEMPLATE_ART: Record<string, string> = {
  "work out": "/cards/workout.svg",
  read: "/cards/read.svg",
  "ship something": "/cards/ship.svg",
  meditate: "/cards/meditate.svg",
  "no phone at night": "/cards/nophone.svg",
};

export function cardArtFor(pact: Pick<Pact, "title" | "card_art">): CardArt {
  // Resolve against the Vite base so the returned `src` works under a subpath
  // (GitHub Pages) as well as at root (dev / Tauri). Wrapped here exactly once —
  // every consumer reads `.src` directly, none re-prefix.
  if (pact.card_art) return { kind: "photo", src: asset(pact.card_art), title: pact.title };
  const src = TEMPLATE_ART[pact.title.trim().toLowerCase()];
  return src ? { kind: "art", src: asset(src) } : { kind: "glyph", title: pact.title };
}

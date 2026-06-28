import type { Pact } from "../types";

export type CardArt = { kind: "art"; src: string } | { kind: "glyph"; title: string };

const TEMPLATE_ART: Record<string, string> = {
  "work out": "/cards/workout.svg",
  read: "/cards/read.svg",
  "ship something": "/cards/ship.svg",
  meditate: "/cards/meditate.svg",
  "no phone at night": "/cards/nophone.svg",
};

export function cardArtFor(pact: Pick<Pact, "title">): CardArt {
  const src = TEMPLATE_ART[pact.title.trim().toLowerCase()];
  return src ? { kind: "art", src } : { kind: "glyph", title: pact.title };
}

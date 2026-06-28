import { describe, it, expect } from "vitest";
import { cardArtFor } from "./cardArt";

describe("cardArtFor", () => {
  it("returns photo variant first when card_art is set", () => {
    expect(cardArtFor({ title: "My custom goal", card_art: "/create/create_3.png" })).toEqual({
      kind: "photo",
      src: "/create/create_3.png",
      title: "My custom goal",
    });
  });
  it("maps template titles to baked art when card_art is null", () => {
    expect(cardArtFor({ title: "Work out", card_art: null })).toEqual({ kind: "art", src: "/cards/workout.svg" });
    expect(cardArtFor({ title: "  read ", card_art: null })).toEqual({ kind: "art", src: "/cards/read.svg" });
    expect(cardArtFor({ title: "No phone at night", card_art: null })).toEqual({ kind: "art", src: "/cards/nophone.svg" });
  });
  it("falls back to a glyph front for custom goals without card_art", () => {
    expect(cardArtFor({ title: "50 pushups", card_art: null })).toEqual({ kind: "glyph", title: "50 pushups" });
  });
  it("ignores empty-string card_art and falls through to template/glyph", () => {
    expect(cardArtFor({ title: "Work out", card_art: "" })).toEqual({ kind: "art", src: "/cards/workout.svg" });
    expect(cardArtFor({ title: "50 pushups", card_art: "" })).toEqual({ kind: "glyph", title: "50 pushups" });
  });
});

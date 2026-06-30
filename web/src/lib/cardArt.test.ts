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
  it("matches templates by keyword inside descriptive titles", () => {
    expect(cardArtFor({ title: "Work out 5x this week (LIVE)", card_art: null })).toEqual({ kind: "art", src: "/cards/workout.svg" });
    expect(cardArtFor({ title: "Run 3x a week", card_art: null })).toEqual({ kind: "art", src: "/cards/workout.svg" });
    expect(cardArtFor({ title: "Read 20 minutes", card_art: null })).toEqual({ kind: "art", src: "/cards/read.svg" });
    expect(cardArtFor({ title: "No phone after 10pm", card_art: null })).toEqual({ kind: "art", src: "/cards/nophone.svg" });
    expect(cardArtFor({ title: "Meditate each morning", card_art: null })).toEqual({ kind: "art", src: "/cards/meditate.svg" });
    expect(cardArtFor({ title: "Ship a feature", card_art: null })).toEqual({ kind: "art", src: "/cards/ship.svg" });
    expect(cardArtFor({ title: "Write 500 words", card_art: null })).toEqual({ kind: "art", src: "/cards/ship.svg" });
    expect(cardArtFor({ title: "Inbox zero daily", card_art: null })).toEqual({ kind: "art", src: "/cards/ship.svg" });
  });
  it("does not false-match a keyword embedded in another word", () => {
    // "spread" contains "read" but isn't a read pact; word boundaries prevent it.
    expect(cardArtFor({ title: "Spread the word", card_art: null })).toEqual({ kind: "glyph", title: "Spread the word" });
  });
  it("falls back to a glyph front for custom goals without card_art", () => {
    expect(cardArtFor({ title: "50 pushups", card_art: null })).toEqual({ kind: "glyph", title: "50 pushups" });
  });
  it("ignores empty-string card_art and falls through to template/glyph", () => {
    expect(cardArtFor({ title: "Work out", card_art: "" })).toEqual({ kind: "art", src: "/cards/workout.svg" });
    expect(cardArtFor({ title: "50 pushups", card_art: "" })).toEqual({ kind: "glyph", title: "50 pushups" });
  });
});

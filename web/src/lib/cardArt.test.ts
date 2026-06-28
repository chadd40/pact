import { describe, it, expect } from "vitest";
import { cardArtFor } from "./cardArt";

describe("cardArtFor", () => {
  it("maps template titles to baked art", () => {
    expect(cardArtFor({ title: "Work out" })).toEqual({ kind: "art", src: "/cards/workout.svg" });
    expect(cardArtFor({ title: "  read " })).toEqual({ kind: "art", src: "/cards/read.svg" });
    expect(cardArtFor({ title: "No phone at night" })).toEqual({ kind: "art", src: "/cards/nophone.svg" });
  });
  it("falls back to a glyph front for custom goals", () => {
    expect(cardArtFor({ title: "50 pushups" })).toEqual({ kind: "glyph", title: "50 pushups" });
  });
});

import { describe, it, expect } from "vitest";
import { MOTIVATION, pickStatement } from "./motivation";

describe("motivation", () => {
  it("has 20 statements", () => expect(MOTIVATION).toHaveLength(20));
  it("picks the first for seed 0 and last for seed→1", () => {
    expect(pickStatement(0)).toBe(MOTIVATION[0]);
    expect(pickStatement(0.999)).toBe(MOTIVATION[MOTIVATION.length - 1]);
  });
  it("always returns a member of the list", () => {
    for (const s of [0, 0.2, 0.5, 0.95]) expect(MOTIVATION).toContain(pickStatement(s));
  });
});

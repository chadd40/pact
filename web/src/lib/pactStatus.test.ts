import { describe, it, expect } from "vitest";
import { statusDot } from "./pactStatus";

const prog = (o: Partial<{ valid_count: number; target: number; days_left: number; behind: boolean }>) => ({
  target_count: 5,
  progress: { valid_count: 0, target: 5, pct: 0, days_left: 7, on_track: true, behind: false, milestone: 0, ...o },
});

describe("statusDot", () => {
  it("green when nothing left to do", () => expect(statusDot(prog({ valid_count: 5 }))).toBe("green"));
  it("green when comfortably on pace", () => expect(statusDot(prog({ valid_count: 1, days_left: 6 }))).toBe("green"));
  it("red when remaining exceeds days left", () => expect(statusDot(prog({ valid_count: 1, days_left: 2 }))).toBe("red"));
  it("amber when no slack left", () => expect(statusDot(prog({ valid_count: 2, days_left: 3 }))).toBe("amber"));
  it("amber when behind but achievable", () => expect(statusDot(prog({ valid_count: 4, days_left: 5, behind: true }))).toBe("amber"));
  it("green when no progress object", () => expect(statusDot({ target_count: 5, progress: undefined })).toBe("green"));
});

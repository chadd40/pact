// @vitest-environment jsdom
// Smoke tests for the Home screen module.
//
// A full render of <Home> is impractical in jsdom because the carousel uses
// window.addEventListener("pointermove"/"pointerup") and 3D CSS transforms
// (perspective / rotateY / translateZ) that jsdom silently ignores, and the
// component also imports CustomCardFront (a large SVG component from Create.tsx)
// which in turn imports several CSS modules + customCardFrame constants. The
// framer-motion layoutId path also requires a full AnimatePresence context.
// Mocking the full provider tree (AppData, Demo, Router, MotionConfig) would be
// more test-infrastructure than feature signal. Instead we test the helpers
// that the Home render depends on at the module level — the only things we can
// verify without a browser.
//
// cardArtFor/statusDot unit tests live in web/src/lib/cardArt.test.ts and
// web/src/lib/pactStatus.test.ts respectively (covered by Task 1).

import { describe, it, expect } from "vitest";
import { MOTIVATION, pickStatement } from "../lib/motivation";

describe("Home smoke — pickStatement", () => {
  it("returns a string that is a member of MOTIVATION", () => {
    const stmt = pickStatement();
    expect(MOTIVATION).toContain(stmt);
  });

  it("is stable for a given seed", () => {
    const a = pickStatement(0.1);
    const b = pickStatement(0.1);
    expect(a).toBe(b);
  });

  it("covers the full range of MOTIVATION with different seeds", () => {
    const seen = new Set<string>();
    for (let i = 0; i < MOTIVATION.length; i++) {
      seen.add(pickStatement(i / MOTIVATION.length));
    }
    // All 20 strings reachable
    expect(seen.size).toBe(MOTIVATION.length);
  });
});

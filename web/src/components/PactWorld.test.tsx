// @vitest-environment jsdom
// web/src/components/PactWorld.test.tsx
//
// Renders PactWorld in standalone mode for an `active` pact and asserts the
// migration invariants: the submit affordance is present, the old At-stake /
// Goes-to chips are gone (stake + charity now live on the card back), the coach
// strip uses the Hermes logo image, and the editorial card-back copy ("On the
// line") is present.
//
// Test seam: PactWorld accepts an optional `initialPact` prop used ONLY here.
// Mocking the live `api.getPact`/`getCoach`/`packet` chain plus the full
// AppData/Demo/Clock/Router/motion provider tree to drive the first render would
// be far more test-infrastructure than feature signal (see Home.smoke.test.tsx
// for the same trade-off). `initialPact` lets us render the real component tree
// (CardBack, panel state machine, coach strip) deterministically without network.

import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PactWorld } from "./PactWorld";
import { AppDataContext, type AppData } from "../data";
import { DemoContext } from "../App";
import type { Pact } from "../types";

// Stub demo context — PactWorld only reads bump/signalChange, and with
// `initialPact` supplied it never invokes the demo actions.
const DEMO = {
  nowIso: null,
  setNow: () => {},
  refreshNow: async () => {},
  bump: 0,
  signalChange: () => {},
  busy: null,
  doSeed: async () => {},
  doAdvance: async () => {},
  doReset: async () => {},
};

// Minimal AppData + provider tree. PactWorld consumes useAppData (charityById),
// useDemo (bump/signalChange), and useClock (nowMs) — but with `initialPact`
// supplied it never touches the demo actions, so a light stub suffices.
const CHARITY = {
  id: "amf",
  name: "Against Malaria Foundation",
  donation_url: "",
  allowed_domains: [],
  category: "global-health",
  description: "Bed nets.",
  default_amounts: [],
  checkout_kind: "link",
  stamp: "/charities/amf.svg",
};

const APP_DATA: AppData = {
  pacts: [],
  pactsLoaded: true,
  charities: [CHARITY],
  charityById: { amf: CHARITY },
};

function activePact(): Pact {
  return {
    id: "p1",
    owner: "demo",
    original_prompt: "",
    title: "Work out",
    goal: "Move your body",
    timezone: "UTC",
    deadline_at: new Date(Date.now() + 86400_000).toISOString(),
    target_count: 20,
    distinct_days: true,
    days_per_week: 5,
    weeks: 4,
    recommended_stake_cents: 20000,
    stake_amount_cents: 20000,
    currency: "usd",
    charity_id: "amf",
    charity_url: "",
    agent: "Hermes",
    card_art: null,
    proof_source: "photo",
    freezes_allowed: 0,
    freezes_used: 0,
    freeze_extension_hours: 0,
    rubric: {
      modality: "photo",
      require_token: false,
      must_show: [],
      reject_if: [],
      min_distinct_days: 0,
      count_target: 20,
      rest_if_injured_counts: false,
      rigor_floor: {},
    },
    status: "active",
    stake_state: "committed",
    spend_request_id: null,
    created_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    verdict_at: null,
    dispute_window_closes_at: null,
    progress: {
      valid_count: 3,
      target: 20,
      pct: 15,
      days_left: 2,
      on_track: true,
      behind: false,
      milestone: 0,
    },
    cadence: {
      days_per_week: 5,
      weeks: 4,
      week_number: 1,
      this_week_valid: 3,
      this_week_target: 5,
    },
  };
}

function renderWorld(flipFrom?: { x: number; y: number; width: number; height: number }) {
  const entry = flipFrom
    ? { pathname: "/pact/p1", state: { flipFrom } }
    : { pathname: "/pact/p1" };
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <DemoContext.Provider value={DEMO}>
        <AppDataContext.Provider value={APP_DATA}>
          <PactWorld pactId="p1" mode="standalone" initialPact={activePact()} />
        </AppDataContext.Provider>
      </DemoContext.Provider>
    </MemoryRouter>
  );
}

describe("PactWorld (active, standalone)", () => {
  afterEach(() => cleanup());

  it("renders the submit affordance", () => {
    renderWorld();
    expect(screen.getByText(/submit/i)).toBeTruthy();
  });

  it("does NOT render the old At stake / Goes to chips", () => {
    renderWorld();
    expect(screen.queryByText(/^At stake$/i)).toBeNull();
    expect(screen.queryByText(/^Goes to$/i)).toBeNull();
  });

  it("renders the Hermes logo in the coach strip", () => {
    const { container } = renderWorld();
    const imgs = Array.from(container.querySelectorAll("img"));
    expect(imgs.some((img) => (img.getAttribute("src") ?? "").includes("Hermes.svg"))).toBe(true);
  });

  it("renders the editorial card-back commitment copy", () => {
    renderWorld();
    // "On the line" is the card-back stake eyebrow (exact text) — proof the live
    // pact feeds CardBack. (The panel lede also contains "is on the line", so we
    // match the eyebrow's exact node rather than a loose substring.)
    expect(screen.getByText("On the line")).toBeTruthy();
    // And the card-back commitment eyebrow.
    expect(screen.getByText("The commitment")).toBeTruthy();
  });

  // ── Flip-open entry animation (Task 8) ──────────────────────────────────────
  it("renders the two-faced flip (front art + editorial back)", () => {
    const { container } = renderWorld();
    // The card is a true two-faced flip: an outer wrapper, a preserve-3d flip
    // container, and front + back faces. Both faces must be in the DOM so a face
    // is always visible while the container rotates.
    expect(container.querySelector(".world-flip")).toBeTruthy();
    expect(container.querySelector(".world-face-front")).toBeTruthy();
    expect(container.querySelector(".world-face-back")).toBeTruthy();
  });

  it("runs the entry treatment when navigation state carries a flipFrom rect", () => {
    const { container } = renderWorld({ x: 10, y: 10, width: 210, height: 300 });
    const world = container.querySelector(".world");
    // The FLIP is driven by a `.world--entering` class on the root that stays on
    // until the transition ends (jsdom never fires transitionend, so it persists).
    expect(world?.classList.contains("world--entering")).toBe(true);
    // The wrapper carries the inverted position transform on first paint.
    const wrap = container.querySelector(".world-card") as HTMLElement | null;
    expect(wrap?.style.transform ?? "").not.toBe("");
    // While entering, the flip container is NOT in its rest (back-showing) class —
    // it starts at 0° (front) and animates to the back.
    const flip = container.querySelector(".world-flip");
    expect(flip?.classList.contains("world-flip--rest")).toBe(false);
  });

  it("does NOT run the entry treatment with no flipFrom (direct visit)", () => {
    const { container } = renderWorld();
    const world = container.querySelector(".world");
    expect(world?.classList.contains("world--entering")).toBe(false);
    const wrap = container.querySelector(".world-card") as HTMLElement | null;
    expect(wrap?.style.transform ?? "").toBe("");
    // At rest (direct visit) the flip container shows the editorial back via the
    // CSS rest class (rotateY 180°), with no inline transform.
    const flip = container.querySelector(".world-flip") as HTMLElement | null;
    expect(flip?.classList.contains("world-flip--rest")).toBe(true);
    expect(flip?.style.transform ?? "").toBe("");
  });
});

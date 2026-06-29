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

import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { MemoryRouter } from "react-router-dom";
import { PactWorld } from "./PactWorld";
import { AppDataContext, type AppData } from "../data";
import { DemoContext } from "../App";
import { api } from "../api";
import type { DonationReceipt, Pact, Packet, Proof } from "../types";

const here = dirname(fileURLToPath(import.meta.url));
const appCss = readFileSync(resolve(here, "../screens/app.css"), "utf8");
const PAPER_TURN = "transform .74s cubic-bezier(.18,.78,.22,1)";

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

function pactWithStatus(status: Pact["status"], stakeState: Pact["stake_state"]): Pact {
  return {
    ...activePact(),
    status,
    stake_state: stakeState,
    spend_request_id: status === "donated" || status === "donation_failed" ? "sr_live_12345678" : null,
    verdict_at: new Date().toISOString(),
  };
}

function renderWorld(
  flipFrom?: { x: number; y: number; width: number; height: number },
  pact: Pact = activePact()
) {
  const entry = flipFrom
    ? { pathname: "/pact/p1", state: { flipFrom } }
    : { pathname: "/pact/p1" };
  return render(
    <MemoryRouter
      initialEntries={[entry]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <DemoContext.Provider value={DEMO}>
        <AppDataContext.Provider value={APP_DATA}>
          <PactWorld pactId="p1" initialPact={pact} />
        </AppDataContext.Provider>
      </DemoContext.Provider>
    </MemoryRouter>
  );
}

describe("PactWorld (active, standalone)", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("renders the submit affordance", () => {
    renderWorld();
    expect(screen.getByText(/submit/i)).toBeTruthy();
  });

  it("asks whether a first proof is happening now before choosing upload or code", () => {
    const { container } = renderWorld();

    fireEvent.click(screen.getByRole("button", { name: /submit today's proof/i }));

    expect(screen.queryByRole("dialog", { name: /submit evidence/i })).toBeNull();
    expect(screen.getByText(/Is this happening now/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /yes, use a fresh code/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /no, upload evidence/i })).toBeTruthy();
    expect(container.querySelector(".pd-proof-panel")?.getAttribute("data-proof-flow")).toBe("choice");
    expect(container.querySelector(".pd-proof-rail")).toBeTruthy();
    expect(container.querySelectorAll(".pd-proof-step")).toHaveLength(3);
    expect(container.querySelector(".pd-proof-step.is-active")?.textContent).toContain("Choose mode");
    expect(screen.queryByText(/Prototype/i)).toBeNull();
  });

  it("uploads an existing first proof directly from the inline prompt", async () => {
    const pact = activePact();
    const file = new File(["proof"], "proof.png", { type: "image/png" });
    let resolveUpload!: (proof: Proof) => void;
    const uploadPromise = new Promise<Proof>((resolve) => { resolveUpload = resolve; });
    const clickInput = vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(() => {});
    vi.spyOn(api, "proofToken").mockResolvedValue({ token: "PACT-YES", expires_at: null });
    vi.spyOn(api, "uploadProofImage").mockReturnValue(uploadPromise);
    vi.spyOn(api, "getPact").mockResolvedValue(pact);
    vi.spyOn(api, "getCoach").mockResolvedValue([]);

    const { container } = renderWorld(undefined, pact);

    fireEvent.click(screen.getByRole("button", { name: /submit today's proof/i }));
    fireEvent.click(screen.getByRole("button", { name: /no, upload evidence/i }));

    expect(clickInput).toHaveBeenCalled();

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    expect(await screen.findByRole("button", { name: /analyzing proof/i })).toBeTruthy();
    await waitFor(() => expect(api.uploadProofImage).toHaveBeenCalledWith("p1", "PACT-YES", file));
    resolveUpload(proof());
    await waitFor(() => expect(screen.getByRole("button", { name: /proof verified/i })).toBeTruthy());
    expect(screen.queryByText(/Capture your proof/i)).toBeNull();
  });

  it("shows a live countdown beside a fresh proof code", async () => {
    const expiresAt = new Date(Date.now() + 600_000).toISOString();
    vi.spyOn(api, "getProofs").mockResolvedValue([]);
    vi.spyOn(api, "proofToken").mockResolvedValue({
      token: "PACT-NOW",
      expires_at: expiresAt,
    } as Awaited<ReturnType<typeof api.proofToken>>);

    renderWorld(undefined, activePact());

    fireEvent.click(screen.getByRole("button", { name: /submit today's proof/i }));
    fireEvent.click(screen.getByRole("button", { name: /yes, use a fresh code/i }));

    expect(await screen.findByText(/fresh proof code/i)).toBeTruthy();
    expect(screen.getByText("PACT-NOW")).toBeTruthy();
    expect(screen.getByText(/expires in (10:00|9:59)/i)).toBeTruthy();
  });

  it("turns the primary proof button into the coded-photo upload action", async () => {
    const clickInput = vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(() => {});
    vi.spyOn(api, "getProofs").mockResolvedValue([]);
    vi.spyOn(api, "proofToken").mockResolvedValue({
      token: "PACT-NOW",
      expires_at: null,
    } as Awaited<ReturnType<typeof api.proofToken>>);

    const { container } = renderWorld(undefined, activePact());

    fireEvent.click(screen.getByRole("button", { name: /submit today's proof/i }));
    fireEvent.click(screen.getByRole("button", { name: /yes, use a fresh code/i }));

    expect(await screen.findByText("PACT-NOW")).toBeTruthy();
    const primary = container.querySelector(".pd-submit") as HTMLButtonElement;
    expect(primary.textContent).toMatch(/upload coded photo/i);

    fireEvent.click(primary);

    expect(clickInput).toHaveBeenCalled();
    expect(container.querySelector(".pd-proof-panel")?.getAttribute("data-proof-flow")).toBe("choosing");
  });

  it("opens the native picker directly after the first proof has already been submitted", async () => {
    const clickInput = vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(() => {});
    vi.spyOn(api, "getProofs").mockResolvedValue([proof()]);

    renderWorld();

    await waitFor(() => expect(api.getProofs).toHaveBeenCalledWith("p1"));
    fireEvent.click(screen.getByRole("button", { name: /submit today's proof/i }));

    expect(clickInput).toHaveBeenCalled();
    expect(screen.queryByText(/Fresh proof code/i)).toBeNull();
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

  it("opens with one paper-card turn from the clicked card to the editorial back", async () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      const el = this as HTMLElement;
      const rect = el.classList.contains("world-card")
        ? { x: 260, y: 88, width: 416, height: 582 }
        : { x: 0, y: 0, width: 0, height: 0 };
      return {
        ...rect,
        top: rect.y,
        left: rect.x,
        right: rect.x + rect.width,
        bottom: rect.y + rect.height,
        toJSON: () => rect,
      } as DOMRect;
    });

    const { container } = renderWorld({ x: 44, y: 172, width: 210, height: 300 });
    const wrap = container.querySelector(".world-card") as HTMLElement;
    const flip = container.querySelector(".world-flip") as HTMLElement;

    await waitFor(() => expect(flip.style.transform).toBe("rotateY(180deg)"));

    expect(wrap.style.transition).toBe(PAPER_TURN);
    expect(flip.style.transition).toBe(PAPER_TURN);
    expect(flip.style.transform).not.toMatch(/rotateY\((?:[2-9]\d{2,}|[1-9]\d{3,})deg\)/);
  });

  it("gives the opening card paper depth instead of a flat backing", () => {
    expect(appCss).toMatch(/\.world-card\s*\{[\s\S]*transform-style:\s*preserve-3d;/);
    expect(appCss).toContain(".world-flip::before");
    expect(appCss).toMatch(/\.world-flip::before[\s\S]*translateZ\(-2px\)/);
    expect(appCss).toMatch(/\.world-flip::after[\s\S]*inset 0 1px 0 rgba\(255, 248, 232/);
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

  it("renders donated as approved but receipt-unconfirmed until evidence is recorded", () => {
    renderWorld(undefined, pactWithStatus("donated", "executed"));
    expect(screen.getByText("Donation approved")).toBeTruthy();
    expect(screen.getByText("Receipt unconfirmed")).toBeTruthy();
    expect(screen.getByRole("button", { name: /record receipt/i })).toBeTruthy();
    // The completion is agent-driven (it pays the charity), not a UI dead-end.
    expect(screen.getByText(/your agent pays the charity/i)).toBeTruthy();
  });

  it("provisions the approved checkout card without exposing the PAN", async () => {
    const donated = pactWithStatus("donated", "executed");
    vi.spyOn(api, "provisionDonationCard").mockResolvedValue({
      provisioned: true,
      last4: "4242",
      brand: "visa",
      exp_month: 12,
      exp_year: 2030,
      mode: "test",
    });

    renderWorld(undefined, donated);
    fireEvent.click(screen.getByRole("button", { name: /provision checkout card/i }));

    await waitFor(() => expect(api.provisionDonationCard).toHaveBeenCalledWith("p1"));
    expect(screen.getByText(/Checkout card ready/i)).toBeTruthy();
    expect(screen.getByText(/visa/i)).toBeTruthy();
    expect(screen.getByText(/•••• 4242/i)).toBeTruthy();
    expect(document.body.textContent).not.toContain("4242424242424242");
  });

  it("renders donation_failed as not completed, not as a receipt", () => {
    renderWorld(undefined, pactWithStatus("donation_failed", "error"));
    expect(screen.getByText("Donation not completed")).toBeTruthy();
    expect(screen.getByText("No transfer was confirmed.")).toBeTruthy();
    expect(screen.queryByText("Donation approved")).toBeNull();
    expect(screen.queryByText("Record receipt")).toBeNull();
  });

  it("validates empty receipt submission without calling the backend", () => {
    const record = vi.spyOn(api, "recordDonationReceipt");
    renderWorld(undefined, pactWithStatus("donated", "executed"));

    fireEvent.click(screen.getByRole("button", { name: /record receipt/i }));

    expect(screen.getByText("Enter the receipt number or URL.")).toBeTruthy();
    expect(record).not.toHaveBeenCalled();
  });

  it("records URL receipts as URLs and refreshes to the confirmed receipt state", async () => {
    const donated = pactWithStatus("donated", "executed");
    const url = "https://charity.example/receipts/AMF-123";
    vi.spyOn(api, "recordDonationReceipt").mockResolvedValue(receiptFor(donated, { receipt_url: url }));
    vi.spyOn(api, "getPact").mockResolvedValue(donated);
    vi.spyOn(api, "getCoach").mockResolvedValue([]);
    vi.spyOn(api, "packet").mockResolvedValue(packetFor(donated, {
      receipt_status: "manual_receipt",
      receipt_url: url,
      confirmed_at: "2026-06-24T12:00:00Z",
    }));

    renderWorld(undefined, donated);
    fireEvent.change(screen.getByLabelText(/charity receipt number or url/i), {
      target: { value: url },
    });
    fireEvent.click(screen.getByRole("button", { name: /record receipt/i }));

    await waitFor(() => {
      expect(api.recordDonationReceipt).toHaveBeenCalledWith("p1", expect.objectContaining({
        receipt_ref: null,
        receipt_url: url,
      }));
    });
    await waitFor(() => expect(screen.getByText(url)).toBeTruthy());
    expect(screen.queryByRole("button", { name: /record receipt/i })).toBeNull();
  });

  it("records non-URL receipts as reference IDs", async () => {
    const donated = pactWithStatus("donated", "executed");
    vi.spyOn(api, "recordDonationReceipt").mockResolvedValue(receiptFor(donated, { receipt_ref: "AMF-123" }));
    vi.spyOn(api, "getPact").mockResolvedValue(donated);
    vi.spyOn(api, "getCoach").mockResolvedValue([]);
    vi.spyOn(api, "packet").mockResolvedValue(packetFor(donated, {
      receipt_status: "manual_receipt",
      receipt_ref: "AMF-123",
      confirmed_at: "2026-06-24T12:00:00Z",
    }));

    renderWorld(undefined, donated);
    fireEvent.change(screen.getByLabelText(/charity receipt number or url/i), {
      target: { value: " AMF-123 " },
    });
    fireEvent.click(screen.getByRole("button", { name: /record receipt/i }));

    await waitFor(() => {
      expect(api.recordDonationReceipt).toHaveBeenCalledWith("p1", expect.objectContaining({
        receipt_ref: "AMF-123",
        receipt_url: null,
      }));
    });
    await waitFor(() => expect(screen.getByText("AMF-123")).toBeTruthy());
  });
});

function receiptFor(pact: Pact, overrides: Partial<DonationReceipt> = {}): DonationReceipt {
  return {
    pact_id: pact.id,
    receipt_status: "manual_receipt",
    receipt_source: "manual",
    receipt_ref: null,
    receipt_url: null,
    receipt_artifact_path: null,
    confirmed_at: "2026-06-24T12:00:00Z",
    confirmation_notes: "Entered by the owner in Pact.",
    ...overrides,
  };
}

function proof(): Proof {
  return {
    id: "proof_1",
    pact_id: "p1",
    modality: "photo",
    received_at: "2026-06-28T12:00:00Z",
    day_bucket: "2026-06-28",
    token_issued: "PACT-123",
    token_ok: true,
    phash: "abc",
    dup_of: null,
    artifact_path: "/tmp/proof.png",
    status: "passed",
    judge_reason: "ok",
    judge_checklist: {},
  };
}

function packetFor(pact: Pact, verdict: Partial<Packet["verdict"]> = {}): Packet {
  return {
    pact,
    proofs: [],
    verdict: {
      status: pact.status,
      banner: "donated",
      valid_proof_count: 0,
      target_count: pact.target_count,
      freezes_used: 0,
      summary: "Donation completed.",
      payment_action: "donation_executed",
      payment_ref: pact.spend_request_id,
      receipt_artifact_path: null,
      receipt_status: "unconfirmed",
      receipt_source: null,
      receipt_ref: null,
      receipt_url: null,
      confirmed_at: null,
      ...verdict,
    },
    honesty_note: "",
    coaching_log: [],
  };
}

// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { StakeApprovalModal } from "./StakeApprovalModal";
import { api } from "../api";
import type { Pact } from "../types";

vi.mock("../api", () => ({
  api: {
    stakeConfirm: vi.fn(),
  },
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

function pact(status: Pact["status"]): Pact {
  return {
    id: "p1",
    owner: "owner@example.com",
    original_prompt: "",
    title: "Train",
    goal: "Train four times",
    timezone: "UTC",
    deadline_at: new Date(Date.now() + 86400_000).toISOString(),
    target_count: 4,
    distinct_days: true,
    days_per_week: 4,
    weeks: 2,
    recommended_stake_cents: 5000,
    stake_amount_cents: 5000,
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
      count_target: 4,
      rest_if_injured_counts: false,
      rigor_floor: {},
    },
    status,
    stake_state: "committed",
    spend_request_id: "sr_123",
    created_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    verdict_at: null,
    dispute_window_closes_at: null,
  };
}

async function flushPromises() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("StakeApprovalModal", () => {
  it("shows the waiting spinner and confirms the stake on mount", async () => {
    vi.useFakeTimers();
    vi.mocked(api.stakeConfirm).mockResolvedValue(pact("active"));
    render(<StakeApprovalModal pact={pact("awaiting_stake")} onApproved={vi.fn()} />);

    expect(screen.getByText(/waiting for link approval/i)).toBeTruthy();
    await flushPromises();
    expect(api.stakeConfirm).toHaveBeenCalledWith("p1");
  });

  it("flips to Approved and fires onApproved once active and the spin beat elapses", async () => {
    vi.useFakeTimers();
    vi.mocked(api.stakeConfirm).mockResolvedValue(pact("active"));
    const onApproved = vi.fn();
    render(<StakeApprovalModal pact={pact("awaiting_stake")} onApproved={onApproved} />);
    await flushPromises();

    // Still spinning before the demo beat elapses.
    expect(onApproved).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(10_000);
      await Promise.resolve();
    });
    expect(screen.getByText(/approved/i)).toBeTruthy();

    await act(async () => {
      vi.advanceTimersByTime(1_200);
      await Promise.resolve();
    });
    expect(onApproved).toHaveBeenCalledTimes(1);
    expect(onApproved).toHaveBeenCalledWith(expect.objectContaining({ status: "active" }));
  });

  it("keeps waiting while the spend is still unapproved, then approves when it lands", async () => {
    vi.useFakeTimers();
    vi.mocked(api.stakeConfirm)
      .mockResolvedValueOnce(pact("awaiting_stake"))
      .mockResolvedValue(pact("active"));
    const onApproved = vi.fn();
    render(<StakeApprovalModal pact={pact("awaiting_stake")} onApproved={onApproved} />);
    await flushPromises();

    // First poll returned awaiting → still spinning, no approval yet.
    expect(onApproved).not.toHaveBeenCalled();
    expect(screen.getByText(/waiting for link approval/i)).toBeTruthy();

    // Second poll (at the 2s interval) lands active → schedules the approved beat.
    await act(async () => { vi.advanceTimersByTime(2_000); });
    await flushPromises();

    // Advance past the minimum spin beat, then the done beat.
    await act(async () => { vi.advanceTimersByTime(10_000); });
    await flushPromises();
    await act(async () => { vi.advanceTimersByTime(1_200); });
    await flushPromises();

    expect(onApproved).toHaveBeenCalledTimes(1);
  });
});

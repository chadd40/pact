// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { LinkModal } from "./LinkModal";
import { api } from "../api";
import type { DonationState, Pact, RuntimeInfo } from "../types";

vi.mock("../api", () => ({
  api: {
    runtime: vi.fn(),
    donationInitiate: vi.fn(),
    donationApprove: vi.fn(),
    donationStatus: vi.fn(),
  },
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

function runtime(liveMoneyEnabled: boolean): RuntimeInfo {
  return {
    payment_mode: liveMoneyEnabled ? "link_cli" : "test",
    link_mode: liveMoneyEnabled ? "live" : "dry_run",
    reasoning_mode: "test",
    auth_mode: "local_dev",
    live_money_enabled: liveMoneyEnabled,
  };
}

function donation(state: DonationState["state"]): DonationState {
  return {
    state,
    status: state === "donated" ? "donated" : "donation_pending",
    stake_state: state === "donated" ? "executed" : "executing",
    spend_request_id: "sr_123",
  };
}

function pact(): Pact {
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
    weeks: 1,
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
    status: "donation_pending",
    stake_state: "executing",
    spend_request_id: null,
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

describe("LinkModal", () => {
  it("does not auto-approve the Link request when live money is enabled", async () => {
    vi.useFakeTimers();
    vi.mocked(api.runtime).mockResolvedValue(runtime(true));
    vi.mocked(api.donationInitiate).mockResolvedValue(donation("awaiting_approval"));
    vi.mocked(api.donationStatus).mockResolvedValue(donation("awaiting_approval"));
    vi.mocked(api.donationApprove).mockResolvedValue(donation("donated"));

    render(
      <LinkModal
        pact={pact()}
        charityName="Against Malaria Foundation"
        onClose={vi.fn()}
        onDonated={vi.fn()}
      />
    );
    await flushPromises();

    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));
    await flushPromises();

    expect(api.donationInitiate).toHaveBeenCalledWith("p1");
    expect(screen.getByText(/approve in your link app/i)).toBeTruthy();

    await act(async () => {
      vi.advanceTimersByTime(5_500);
      await Promise.resolve();
    });

    expect(api.donationStatus).toHaveBeenCalled();
    expect(api.donationApprove).not.toHaveBeenCalled();
  });

  it("keeps demo auto-approval when live money is disabled", async () => {
    vi.useFakeTimers();
    vi.mocked(api.runtime).mockResolvedValue(runtime(false));
    vi.mocked(api.donationInitiate).mockResolvedValue(donation("awaiting_approval"));
    vi.mocked(api.donationStatus).mockResolvedValue(donation("awaiting_approval"));
    vi.mocked(api.donationApprove).mockResolvedValue(donation("donated"));

    render(
      <LinkModal
        pact={pact()}
        charityName="Against Malaria Foundation"
        onClose={vi.fn()}
        onDonated={vi.fn()}
      />
    );
    await flushPromises();

    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));
    await flushPromises();

    await act(async () => {
      vi.advanceTimersByTime(2_700);
      await Promise.resolve();
    });

    expect(api.donationApprove).toHaveBeenCalledWith("p1");
  });
});

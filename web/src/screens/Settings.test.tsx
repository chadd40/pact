// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Settings } from "./Settings";
import { api, DEMO_OWNER } from "../api";
import type { LinkStatus } from "../types";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    api: {
      linkStatus: vi.fn(),
      linkConnect: vi.fn(),
      mintAgentToken: vi.fn(),
    },
  };
});

function linkStatus(connected: boolean): LinkStatus {
  return {
    owner: DEMO_OWNER,
    connected,
    funding_ref: connected ? "link_pm_test" : null,
    payment_method_id: connected ? "pm_123" : null,
    payment_method_label: connected ? "Visa" : null,
    payment_method_last4: connected ? "4242" : null,
    error: null,
  };
}

describe("Settings", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it("shows live-safe funding copy and connected Link details", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus(true));

    render(<Settings />);

    await waitFor(() => expect(screen.getByText(/connected/i)).toBeTruthy());
    expect(screen.getByText(/Pact never holds your money/i).textContent).not.toMatch(/\btest\b/i);
    expect(screen.getByText(/Visa .*4242/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /connect link/i })).toBeNull();
  });

  it("mints a token, copies it, and clears it when the owner changes", async () => {
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus(false));
    vi.mocked(api.mintAgentToken).mockResolvedValue({
      owner: DEMO_OWNER,
      token: "pat_1234567890abcdefghijklmnopqrstuvwxyz",
    });

    render(<Settings />);

    fireEvent.click(await screen.findByRole("button", { name: /generate token/i }));
    await waitFor(() => expect(screen.getByText("pat_1234567890abcdefghijklmnopqrstuvwxyz")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /copy/i }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("pat_1234567890abcdefghijklmnopqrstuvwxyz"));

    const ownerInput = screen.getByDisplayValue(DEMO_OWNER);
    fireEvent.change(ownerInput, {
      target: { value: " next-owner@example.com " },
    });
    fireEvent.blur(ownerInput);

    await waitFor(() => expect(screen.queryByText("pat_1234567890abcdefghijklmnopqrstuvwxyz")).toBeNull());
    expect(window.localStorage.getItem("pact.localOwner")).toBe("next-owner@example.com");
  });
});

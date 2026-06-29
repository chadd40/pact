// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Settings } from "./Settings";
import { api, DEMO_OWNER } from "../api";
import type { ConnectorHealth, LinkStatus, RuntimeInfo } from "../types";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    api: {
      linkStatus: vi.fn(),
      linkPreflight: vi.fn(),
      linkConnect: vi.fn(),
      mintAgentToken: vi.fn(),
      connectorHealth: vi.fn(),
      runtime: vi.fn(),
    },
  };
});

function runtime(liveMoneyEnabled = false): RuntimeInfo {
  return {
    payment_mode: liveMoneyEnabled ? "link_cli" : "test_link",
    link_mode: liveMoneyEnabled ? "live" : "dry_run",
    reasoning_mode: "hybrid",
    auth_mode: "local_dev",
    live_money_enabled: liveMoneyEnabled,
  };
}

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

function connectorHealth(status: "missing" | "ready" = "ready"): ConnectorHealth {
  return {
    owner: DEMO_OWNER,
    runtime: {
      reasoning_mode: "hybrid",
      auth_mode: "local_dev",
      base_url: "http://127.0.0.1:8000",
    },
    agent_token: {
      status,
      token_prefix: status === "ready" ? "pat_abcdef12" : null,
      expires_at: null,
      last_used_at: null,
      scopes: status === "ready" ? ["claim_tasks", "post_results"] : [],
    },
    worker: {
      status: status === "ready" ? "online" : "offline",
      last_seen_at: status === "ready" ? "2026-06-28T12:00:00+00:00" : null,
      presence_window_seconds: 45,
    },
    capabilities: {
      text: status === "ready",
      vision: status === "ready",
    },
    connectors: [
      {
        key: "hermes",
        name: "Hermes",
        kind: "skill",
        status: "ready",
        installed: true,
        capabilities: ["text", "vision"],
        detail: "Built in.",
        action: "Run /pact serve.",
      },
      {
        key: "mcp",
        name: "MCP",
        kind: "mcp",
        status: status === "ready" ? "ready" : "needs_token",
        installed: status === "ready",
        capabilities: ["text"],
        detail: "Use Pact MCP.",
        action: "Add the Pact MCP server command.",
        command: "pact mcp --base-url http://127.0.0.1:8000 --agent-token <agent-token>",
        config: {},
      },
    ],
    mcp: {
      server_name: "pact",
      command: "pact mcp --base-url http://127.0.0.1:8000 --agent-token <agent-token>",
      config: {},
    },
  };
}

describe("Settings", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  beforeEach(() => {
    vi.mocked(api.runtime).mockResolvedValue(runtime(false));
    vi.mocked(api.linkPreflight).mockResolvedValue(linkStatus(true));
  });

  it("shows live-safe funding copy and connected Link details", async () => {
    vi.mocked(api.runtime).mockResolvedValue(runtime(true));
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus(true));
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    render(<Settings />);

    await waitFor(() => expect(screen.getByText(/connected/i)).toBeTruthy());
    expect(screen.getByText(/Pact never holds your money/i).textContent).not.toMatch(/\btest\b/i);
    expect(screen.getByText(/Visa .*4242/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /connect link/i })).toBeNull();
  });

  it("labels dry-run funding as local-only rather than a real payment method", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue({
      ...linkStatus(true),
      payment_method_id: null,
      payment_method_label: null,
      payment_method_last4: null,
      funding_ref: "test_funding_demo@pact.local",
    });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    render(<Settings />);

    await waitFor(() => expect(screen.getByText(/Local-only Link ready/i)).toBeTruthy());
    expect(screen.getByText(/No real card is connected/i)).toBeTruthy();
    expect(screen.queryByText(/test_funding/i)).toBeNull();
    expect(screen.queryByText(/Connected · Link connector ready/i)).toBeNull();
  });

  it("keeps live Link in setup state when no payment method is ready", async () => {
    vi.mocked(api.runtime).mockResolvedValue(runtime(true));
    const notReadyLink: LinkStatus = {
      ...linkStatus(true),
      ready: false,
      payment_method_id: null,
      payment_method_label: null,
      payment_method_last4: null,
      error: "No usable Link payment method is available",
    };
    vi.mocked(api.linkStatus).mockResolvedValue(notReadyLink);
    vi.mocked(api.linkPreflight).mockResolvedValue(notReadyLink);
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    render(<Settings />);

    await waitFor(() => expect(screen.getByText(/No usable Link payment method is available/i)).toBeTruthy());
    expect(screen.getByRole("button", { name: /connect link/i })).toBeTruthy();
    expect(screen.queryByText(/Connected · Link connector ready/i)).toBeNull();
    expect(screen.queryByText(/Pact never holds your money/i)).toBeNull();
  });

  it("uses live Link preflight to refresh payment-method readiness", async () => {
    vi.mocked(api.runtime).mockResolvedValue(runtime(true));
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus(false));
    vi.mocked(api.linkPreflight).mockResolvedValue({
      ...linkStatus(true),
      ready: true,
      funding_ref: "pm_live_123",
      payment_method_id: "pm_live_123",
    });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    render(<Settings />);

    await waitFor(() => expect(api.linkPreflight).toHaveBeenCalledWith(DEMO_OWNER));
    expect(screen.getByText(/Visa .*4242/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /connect link/i })).toBeNull();
  });

  it("mints a token, copies it, and clears it when the owner changes", async () => {
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus(false));
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth("missing"));
    vi.mocked(api.mintAgentToken).mockResolvedValue({
      owner: DEMO_OWNER,
      token: "pat_1234567890abcdefghijklmnopqrstuvwxyz",
    });

    render(<Settings />);

    fireEvent.click(await screen.findByRole("button", { name: /generate token/i }));
    await waitFor(() => expect(screen.getByText("pat_1234567890abcdefghijklmnopqrstuvwxyz")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /copy agent token/i }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("pat_1234567890abcdefghijklmnopqrstuvwxyz"));

    const ownerInput = screen.getByDisplayValue(DEMO_OWNER);
    fireEvent.change(ownerInput, {
      target: { value: " next-owner@example.com " },
    });
    fireEvent.blur(ownerInput);

    await waitFor(() => expect(screen.queryByText("pat_1234567890abcdefghijklmnopqrstuvwxyz")).toBeNull());
    expect(window.localStorage.getItem("pact.localOwner")).toBe("next-owner@example.com");
  });

  it("shows connector health and the MCP server command", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus(true));
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    render(<Settings />);

    expect(await screen.findByText(/agent connector health/i)).toBeTruthy();
    expect(screen.getByText(/worker online/i)).toBeTruthy();
    expect(screen.getByText(/pat_abcdef12/i)).toBeTruthy();
    expect(screen.getByText(/pact mcp --base-url/i)).toBeTruthy();
  });

  it("surfaces setup endpoints and saves the owner from an explicit action", async () => {
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus(false));
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    render(<Settings />);

    expect(await screen.findByText(/local api/i)).toBeTruthy();
    expect(screen.getByText("http://127.0.0.1:8000")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /copy mcp command/i }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "pact mcp --base-url http://127.0.0.1:8000 --agent-token <agent-token>"
    ));

    const ownerInput = screen.getByDisplayValue(DEMO_OWNER);
    fireEvent.change(ownerInput, {
      target: { value: " new-owner@example.com " },
    });
    fireEvent.click(screen.getByRole("button", { name: /save owner/i }));

    await waitFor(() => expect(window.localStorage.getItem("pact.localOwner")).toBe("new-owner@example.com"));
  });
});

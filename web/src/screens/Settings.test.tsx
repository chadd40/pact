// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Settings } from "./Settings";
import { api, DEMO_OWNER } from "../api";
import type { ConnectorHealth, LinkStatus, Pact, RuntimeInfo, SpendPolicy } from "../types";

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
      getPolicy: vi.fn(),
      setPolicy: vi.fn(),
      listPacts: vi.fn(),
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
    connectors: [],
    mcp: {
      server_name: "pact",
      command: "pact mcp --base-url http://127.0.0.1:8000 --agent-token <agent-token>",
      config: {},
    },
  };
}

function spendPolicy(limit: number | null = null): SpendPolicy {
  return {
    owner: DEMO_OWNER,
    spend_limit_cents: limit,
    charity_allowlist: ["against_malaria_foundation"],
    rail: "nemoguard",
  };
}

function pactWithSigner(signer: string): Pact {
  return { signer_name: signer } as unknown as Pact;
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
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus(true));
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());
    vi.mocked(api.getPolicy).mockResolvedValue(spendPolicy());
    vi.mocked(api.setPolicy).mockImplementation(async (_owner, limit) => spendPolicy(limit));
    vi.mocked(api.listPacts).mockResolvedValue([]);
  });

  it("drops the account id and the billing form entirely", async () => {
    render(<Settings />);

    await screen.findByLabelText(/your name/i);
    expect(screen.queryByText(/account id/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /save owner/i })).toBeNull();
    expect(screen.queryByLabelText(/street/i)).toBeNull();
    expect(screen.queryByLabelText(/postal code/i)).toBeNull();
    expect(screen.queryByText(/billing details/i)).toBeNull();
  });

  it("seeds Your name from a sealed pact's signer name", async () => {
    vi.mocked(api.listPacts).mockResolvedValue([pactWithSigner("Ada Lovelace")]);

    render(<Settings />);

    await screen.findByDisplayValue("Ada Lovelace");
    expect(window.localStorage.getItem("pact.displayName")).toBe("Ada Lovelace");
  });

  it("saves an explicit name to local display storage", async () => {
    render(<Settings />);

    const nameInput = await screen.findByLabelText(/your name/i);
    fireEvent.change(nameInput, { target: { value: "Grace Hopper" } });
    fireEvent.click(screen.getByRole("button", { name: /save name/i }));

    await waitFor(() => expect(window.localStorage.getItem("pact.displayName")).toBe("Grace Hopper"));
  });

  it("shows live-safe Link copy and the connected card", async () => {
    vi.mocked(api.runtime).mockResolvedValue(runtime(true));

    render(<Settings />);

    await waitFor(() => expect(screen.getByText(/Visa .*4242/)).toBeTruthy());
    expect(screen.getByText(/Pact never holds your money/i).textContent).not.toMatch(/\btest\b/i);
    expect(screen.queryByRole("button", { name: /connect link/i })).toBeNull();
  });

  it("labels dry-run funding as local-only rather than a real card", async () => {
    vi.mocked(api.linkPreflight).mockResolvedValue({
      ...linkStatus(true),
      payment_method_id: null,
      payment_method_label: null,
      payment_method_last4: null,
      funding_ref: "test_funding_demo@pact.local",
    });

    render(<Settings />);

    await waitFor(() => expect(screen.getByText(/Local-only Link ready/i)).toBeTruthy());
    expect(screen.getByText(/No real card is connected/i)).toBeTruthy();
    expect(screen.queryByText(/test_funding/i)).toBeNull();
  });

  it("keeps Link in setup state with a connect action when no method is ready", async () => {
    vi.mocked(api.runtime).mockResolvedValue(runtime(true));
    const notReady: LinkStatus = {
      ...linkStatus(true),
      ready: false,
      payment_method_id: null,
      payment_method_label: null,
      payment_method_last4: null,
      error: "No usable Link payment method is available",
    };
    vi.mocked(api.linkPreflight).mockResolvedValue(notReady);

    render(<Settings />);

    await waitFor(() => expect(screen.getByText(/No usable Link payment method is available/i)).toBeTruthy());
    expect(screen.getByRole("button", { name: /connect link/i })).toBeTruthy();
  });

  it("shows the onboard-style serve command and mints a token into it", async () => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth("missing"));
    vi.mocked(api.mintAgentToken).mockResolvedValue({
      owner: DEMO_OWNER,
      token: "pat_1234567890abcdefghij",
    });

    render(<Settings />);

    const before = await screen.findByText(/pact serve --base-url http:\/\/127\.0\.0\.1:8000/i);
    expect(before.textContent).toContain("<paste your token>");

    fireEvent.click(screen.getByRole("button", { name: /generate token/i }));

    await waitFor(() =>
      expect(screen.getByText(/pact serve/i).textContent).toContain("pat_1234567890abcdefghij")
    );

    fireEvent.click(screen.getByRole("button", { name: /copy serve command/i }));
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        "pact serve --base-url http://127.0.0.1:8000 --agent-token pat_1234567890abcdefghij"
      )
    );
  });

  it("folds in connector health and the MCP command", async () => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });

    render(<Settings />);

    expect(await screen.findByText("Token pat_abcdef12")).toBeTruthy();
    expect(screen.getByText(/Worker online/i)).toBeTruthy();
    expect(screen.getByText(/pact mcp --base-url/i)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /copy mcp command/i }));
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        "pact mcp --base-url http://127.0.0.1:8000 --agent-token <agent-token>"
      )
    );
  });

  it("saves the agent spend limit in cents and updates the copy", async () => {
    render(<Settings />);

    const limitInput = await screen.findByRole("spinbutton", { name: /agent spend limit/i });
    fireEvent.change(limitInput, { target: { value: "12.50" } });
    fireEvent.click(screen.getByRole("button", { name: /save limit/i }));

    await waitFor(() => expect(api.setPolicy).toHaveBeenCalledWith(DEMO_OWNER, 1250));
    expect(screen.getByText(/spend up to \$12\.50/i)).toBeTruthy();
    expect(screen.getByText(/NemoGuard enforces this on every spend/i)).toBeTruthy();
  });
});

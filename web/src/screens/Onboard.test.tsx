// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { Onboard } from "./Onboard";
import { api, DEMO_OWNER } from "../api";
import type { ConnectorHealth, LinkStatus, Pact } from "../types";
import type { RuntimeInfo } from "../types";

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
      getPact: vi.fn(),
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

function linkStatus(): LinkStatus {
  return {
    owner: DEMO_OWNER,
    connected: true,
    funding_ref: "link_pm_test",
    error: null,
  };
}

function connectorHealth(): ConnectorHealth {
  return {
    owner: DEMO_OWNER,
    runtime: {
      reasoning_mode: "hybrid",
      auth_mode: "local_dev",
      base_url: "http://127.0.0.1:8000",
    },
    agent_token: {
      status: "ready",
      token_prefix: "pat_onboard12",
      expires_at: null,
      last_used_at: null,
      scopes: ["claim_tasks", "post_results"],
    },
    worker: {
      status: "offline",
      last_seen_at: null,
      presence_window_seconds: 45,
    },
    capabilities: {
      text: false,
      vision: false,
    },
    connectors: [
      {
        key: "mcp",
        name: "MCP",
        kind: "mcp",
        status: "ready",
        installed: true,
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

function connectorHealthNeedsSetup(): ConnectorHealth {
  const health = connectorHealth();
  return {
    ...health,
    agent_token: {
      ...health.agent_token,
      status: "missing",
      token_prefix: null,
      scopes: [],
    },
    worker: {
      ...health.worker,
      status: "offline",
      last_seen_at: null,
    },
    capabilities: {
      text: false,
      vision: false,
    },
    connectors: health.connectors.map((connector) =>
      connector.key === "mcp"
        ? { ...connector, status: "needs_token", installed: false }
        : connector
    ),
  };
}

function pact(): Pact {
  return {
    id: "pact_1",
    owner: DEMO_OWNER,
    original_prompt: "Ship",
    title: "Ship",
    goal: "Ship once",
    timezone: "America/Los_Angeles",
    deadline_at: "2026-07-01T12:00:00Z",
    target_count: 1,
    distinct_days: true,
    recommended_stake_cents: 1000,
    stake_amount_cents: 1000,
    currency: "usd",
    charity_id: "against_malaria_foundation",
    charity_url: "https://againstmalaria.com/donate",
    agent: "your agent",
    proof_source: "manual",
    freezes_allowed: 1,
    freezes_used: 0,
    freeze_extension_hours: 24,
    rubric: {
      modality: "photo",
      require_token: true,
      must_show: ["x"],
      reject_if: [],
      min_distinct_days: 1,
      count_target: 1,
      rest_if_injured_counts: true,
      rigor_floor: {},
    },
    status: "active",
    stake_state: "committed",
    spend_request_id: null,
    created_at: "2026-06-28T12:00:00Z",
    started_at: "2026-06-28T12:00:00Z",
    verdict_at: null,
    dispute_window_closes_at: null,
  };
}

function renderOnboard() {
  return render(
    <MemoryRouter initialEntries={[{ pathname: "/onboard", state: { pactId: "pact_1" } }]}>
      <Routes>
        <Route path="/onboard" element={<Onboard />} />
        <Route path="/dashboard" element={<div>Dashboard route reached</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe("Onboard", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  beforeEach(() => {
    vi.mocked(api.runtime).mockResolvedValue(runtime(false));
    vi.mocked(api.linkPreflight).mockResolvedValue(linkStatus());
  });

  it("refreshes connector health after minting an agent token", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.getPact).mockResolvedValue(pact());
    vi.mocked(api.mintAgentToken).mockResolvedValue({
      owner: DEMO_OWNER,
      token: "pat_onboard1234567890",
    });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    renderOnboard();

    fireEvent.click(await screen.findByRole("button", { name: /generate token/i }));

    await waitFor(() => expect(api.connectorHealth).toHaveBeenCalledWith(DEMO_OWNER));
    expect(screen.getByText(/MCP server ready/i)).toBeTruthy();
    expect(screen.getByText(/worker offline/i)).toBeTruthy();
    expect(screen.getByText(/pact mcp --base-url/i)).toBeTruthy();
  });

  it("presents first-run setup as an agent chat instead of a checklist", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.getPact).mockResolvedValue({ ...pact(), agent: "Hermes" });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    renderOnboard();

    expect(await screen.findByRole("log", { name: /hermes setup chat/i })).toBeTruthy();
    expect(screen.queryByText(/two quick steps/i)).toBeNull();
    expect(screen.getByText(/Link funding check/i)).toBeTruthy();
    expect(screen.getByText(/MCP server ready/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /dashboard/i })).toBeTruthy();
  });

  it("offers a one-word Dashboard handoff inside the ready setup chat", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.getPact).mockResolvedValue({ ...pact(), agent: "Hermes" });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    renderOnboard();

    const dashboard = await screen.findByRole("button", { name: /^dashboard$/i });
    fireEvent.click(dashboard);

    expect(await screen.findByText("Dashboard route reached")).toBeTruthy();
  });

  it("lets the user confirm the local Pact API URL used by the MCP command", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.getPact).mockResolvedValue({ ...pact(), agent: "Hermes" });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    renderOnboard();

    const url = await screen.findByLabelText(/local pact api url/i) as HTMLInputElement;
    expect(url.value).toBe("http://127.0.0.1:8000");
    expect(screen.getByText(/pact mcp --base-url http:\/\/127\.0\.0\.1:8000/i)).toBeTruthy();

    fireEvent.change(url, { target: { value: "http://localhost:9000" } });

    expect(screen.getByText(/pact mcp --base-url http:\/\/localhost:9000/i)).toBeTruthy();
    expect(window.localStorage.getItem("pact.agentBaseUrl")).toBe("http://localhost:9000");
  });

  it("copies the customized MCP command from the setup chat", async () => {
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.getPact).mockResolvedValue({ ...pact(), agent: "Hermes" });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    renderOnboard();

    const url = await screen.findByLabelText(/local pact api url/i) as HTMLInputElement;
    fireEvent.change(url, { target: { value: "http://localhost:9000" } });
    fireEvent.click(screen.getByRole("button", { name: /copy mcp command/i }));

    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "pact mcp --base-url http://localhost:9000 --agent-token <agent-token>",
    ));
    expect(screen.getByRole("button", { name: /copied/i })).toBeTruthy();
  });

  it("labels dry-run funding as local-only in the setup chat", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue({
      ...linkStatus(),
      payment_method_id: null,
      payment_method_label: null,
      payment_method_last4: null,
      funding_ref: "test_funding_demo@pact.local",
    });
    vi.mocked(api.getPact).mockResolvedValue({ ...pact(), agent: "Hermes" });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    renderOnboard();

    await screen.findByRole("log", { name: /hermes setup chat/i });
    expect(screen.queryByText(/test_funding/i)).toBeNull();
    expect(screen.getByText(/Local-only Link ready/i)).toBeTruthy();
    expect(screen.getByText(/No real card is connected/i)).toBeTruthy();
    expect(screen.queryByText(/Connected · Link connector ready/i)).toBeNull();
  });

  it("does not unlock setup when live Link is connected but missing a ready payment method", async () => {
    vi.mocked(api.runtime).mockResolvedValue(runtime(true));
    const notReadyLink: LinkStatus = {
      ...linkStatus(),
      ready: false,
      payment_method_id: null,
      payment_method_label: null,
      payment_method_last4: null,
      error: "No usable Link payment method is available",
    };
    vi.mocked(api.linkStatus).mockResolvedValue(notReadyLink);
    vi.mocked(api.linkPreflight).mockResolvedValue(notReadyLink);
    vi.mocked(api.getPact).mockResolvedValue({ ...pact(), agent: "Hermes" });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    renderOnboard();

    await screen.findByRole("log", { name: /hermes setup chat/i });
    expect(screen.getByText(/No usable Link payment method is available/i)).toBeTruthy();
    expect(screen.getByText(/needs setup/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /connect link/i })).toBeTruthy();
    expect(screen.queryByText(/Connected · Link connector ready/i)).toBeNull();
    expect((screen.getByRole("button", { name: /finish setup to open dashboard/i }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("keeps pact navigation locked until the agent and MCP setup are ready", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.getPact).mockResolvedValue({ ...pact(), agent: "Hermes" });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealthNeedsSetup());

    renderOnboard();

    await screen.findByRole("log", { name: /hermes setup chat/i });
    expect(screen.getByText(/add the local pact mcp server/i)).toBeTruthy();
    expect(screen.getByText("waiting")).toBeTruthy();
    expect((screen.getByRole("button", { name: /finish setup to open dashboard/i }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: /^view pact$/i }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("refreshes live Link with preflight before deciding setup is ready", async () => {
    vi.mocked(api.runtime).mockResolvedValue(runtime(true));
    vi.mocked(api.linkStatus).mockResolvedValue({
      owner: DEMO_OWNER,
      connected: false,
      funding_ref: null,
      error: null,
    });
    vi.mocked(api.linkPreflight).mockResolvedValue({
      owner: DEMO_OWNER,
      connected: true,
      ready: true,
      funding_ref: "pm_live_123",
      payment_method_id: "pm_live_123",
      payment_method_label: "Visa",
      payment_method_last4: "4242",
      error: null,
    });
    vi.mocked(api.getPact).mockResolvedValue({ ...pact(), agent: "Hermes" });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    renderOnboard();

    await waitFor(() => expect(api.linkPreflight).toHaveBeenCalledWith(DEMO_OWNER));
    expect(screen.getByText(/Connected · Visa .*4242/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /^dashboard$/i })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /connect link/i })).toBeNull();
  });
});

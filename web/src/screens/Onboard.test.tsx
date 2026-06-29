// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { Onboard } from "./Onboard";
import { api, DEMO_OWNER } from "../api";
import type { ConnectorHealth, LinkStatus, Pact } from "../types";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    api: {
      linkStatus: vi.fn(),
      linkConnect: vi.fn(),
      mintAgentToken: vi.fn(),
      connectorHealth: vi.fn(),
      getPact: vi.fn(),
    },
  };
});

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

  it("does not surface raw test funding references in the setup chat", async () => {
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
    expect(screen.getByText(/Link connector ready/i)).toBeTruthy();
  });
});

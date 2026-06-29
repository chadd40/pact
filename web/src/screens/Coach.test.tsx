// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Coach } from "./Coach";
import { api, DEMO_OWNER } from "../api";
import type { CoachingMessage, ConnectorHealth, Pact } from "../types";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    api: {
      outbox: vi.fn(),
      connectorHealth: vi.fn(),
    },
  };
});

vi.mock("../App", () => ({
  useDemo: () => ({ bump: 0 }),
}));

vi.mock("../owner", () => ({
  useLocalOwner: () => [DEMO_OWNER],
}));

vi.mock("../data", () => ({
  useAppData: () => ({
    pacts: [
      {
        id: "p1",
        owner: DEMO_OWNER,
        original_prompt: "",
        title: "Morning lift",
        goal: "Train",
        timezone: "America/Los_Angeles",
        deadline_at: "2026-07-01T12:00:00Z",
        target_count: 1,
        distinct_days: true,
        days_per_week: 5,
        weeks: 4,
        recommended_stake_cents: 1000,
        stake_amount_cents: 1000,
        currency: "usd",
        charity_id: "amf",
        charity_url: "",
        agent: "Hermes",
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
          count_target: 1,
          rest_if_injured_counts: false,
          rigor_floor: {},
        },
        status: "active",
        stake_state: "committed",
        spend_request_id: null,
        created_at: "2026-06-28T12:00:00Z",
        started_at: "2026-06-28T12:00:00Z",
        verdict_at: null,
        dispute_window_closes_at: null,
      } satisfies Pact,
    ],
  }),
}));

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
      token_prefix: "pat_abcdef12",
      expires_at: null,
      last_used_at: null,
      scopes: ["claim_tasks", "post_results"],
    },
    worker: {
      status: "online",
      last_seen_at: "2026-06-28T12:00:00+00:00",
      presence_window_seconds: 45,
    },
    capabilities: {
      text: true,
      vision: true,
    },
    connectors: [
      {
        key: "mcp",
        name: "MCP",
        kind: "mcp",
        status: "ready",
        installed: true,
        capabilities: ["text", "vision"],
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

function message(): CoachingMessage {
  return {
    id: "m1",
    pact_id: "p1",
    direction: "outbound",
    trigger: "daily_check",
    pact_state_snapshot: {},
    channel: "in_app",
    body: "Get the lift in before dinner. Keep the proof simple.",
    sent_at: "2026-06-28T14:00:00Z",
    delivered_at: null,
    attachments: [],
  };
}

describe("Coach", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  beforeEach(() => {
    vi.mocked(api.outbox).mockResolvedValue([message()]);
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());
  });

  it("renders an agent console with the same chat surface used by pact chat", async () => {
    const { container } = render(
      <MemoryRouter>
        <Coach />
      </MemoryRouter>
    );

    expect(await screen.findByRole("log", { name: /hermes coach console/i })).toBeTruthy();
    expect(screen.getByText("Get the lift in before dinner. Keep the proof simple.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /open chat for morning lift/i })).toBeTruthy();
    expect(screen.getByLabelText(/hermes coach profile/i)).toBeTruthy();
    expect(screen.getByText(/pact mcp --base-url/i)).toBeTruthy();
    await waitFor(() => expect(container.querySelector(".coach-status-grid")).toBeNull());
  });
});

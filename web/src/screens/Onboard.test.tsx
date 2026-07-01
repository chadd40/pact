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
  return { owner: DEMO_OWNER, connected: true, funding_ref: "link_pm_test", error: null };
}

function connectorHealth(): ConnectorHealth {
  return {
    owner: DEMO_OWNER,
    runtime: { reasoning_mode: "hybrid", auth_mode: "local_dev", base_url: "http://127.0.0.1:8000" },
    agent_token: {
      status: "ready", token_prefix: "pat_onboard12", expires_at: null, last_used_at: null,
      scopes: ["claim_tasks", "post_results"],
    },
    worker: { status: "offline", last_seen_at: null, presence_window_seconds: 45 },
    capabilities: { text: false, vision: false },
    connectors: [{
      key: "mcp", name: "MCP", kind: "mcp", status: "ready", installed: true, capabilities: ["text"],
      detail: "Use Pact MCP.", action: "Add the Pact MCP server command.",
      command: "pact mcp --base-url http://127.0.0.1:8000 --agent-token <agent-token>", config: {},
    }],
    mcp: { server_name: "pact", command: "pact mcp ...", config: {} },
  };
}

function connectorHealthNeedsSetup(): ConnectorHealth {
  const health = connectorHealth();
  return {
    ...health,
    agent_token: { ...health.agent_token, status: "missing", token_prefix: null, scopes: [] },
  };
}

function pact(): Pact {
  return {
    id: "pact_1", owner: DEMO_OWNER, original_prompt: "Ship", title: "Ship", goal: "Ship once",
    timezone: "America/Los_Angeles", deadline_at: "2026-07-01T12:00:00Z", target_count: 1,
    distinct_days: true, recommended_stake_cents: 1000, stake_amount_cents: 1000, currency: "usd",
    charity_id: "against_malaria_foundation", charity_url: "https://againstmalaria.com/donate",
    agent: "your agent", proof_source: "manual", freezes_allowed: 1, freezes_used: 0,
    freeze_extension_hours: 24,
    rubric: { modality: "photo", require_token: true, must_show: ["x"], reject_if: [],
      min_distinct_days: 1, count_target: 1, rest_if_injured_counts: true, rigor_floor: {} },
    status: "active", stake_state: "committed", spend_request_id: null,
    created_at: "2026-06-28T12:00:00Z", started_at: "2026-06-28T12:00:00Z",
    verdict_at: null, dispute_window_closes_at: null,
  };
}

function renderOnboard() {
  return render(
    <MemoryRouter
      initialEntries={[{ pathname: "/onboard", state: { pactId: "pact_1" } }]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Routes>
        <Route path="/onboard" element={<Onboard />} />
        <Route path="/dashboard" element={<div>Dashboard route reached</div>} />
        <Route path="/pact/:id" element={<div>Pact route reached</div>} />
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
    vi.mocked(api.getPact).mockResolvedValue({ ...pact(), agent: "Hermes" });
  });

  it("auto-skips straight to the sealed pact when funding + agent are already set up", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    renderOnboard();

    // A returning / fully-set-up user never sees the setup wall.
    expect(await screen.findByText("Pact route reached")).toBeTruthy();
    expect(screen.queryByRole("region", { name: /setup/i })).toBeNull();
  });

  it("shows the setup sections (Link CLI + connect-agent) when the agent isn't connected yet", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealthNeedsSetup());

    renderOnboard();

    expect(await screen.findByRole("region", { name: /hermes setup/i })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Link CLI" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: /connect your agent/i })).toBeTruthy();
    // Billing + spend limit moved to Settings — no forms, no note here anymore.
    expect(screen.queryByRole("button", { name: /save billing/i })).toBeNull();
    expect(screen.queryByRole("spinbutton", { name: /agent spend limit/i })).toBeNull();
    expect(screen.queryByText(/billing/i)).toBeNull();
    expect((screen.getByRole("button", { name: /finish setup to open dashboard/i }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows a serve command (with the real token) after minting", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealthNeedsSetup());
    vi.mocked(api.mintAgentToken).mockResolvedValue({ owner: DEMO_OWNER, token: "pat_onboard1234567890" });

    renderOnboard();
    fireEvent.click(await screen.findByRole("button", { name: /generate token/i }));

    await waitFor(() => expect(api.mintAgentToken).toHaveBeenCalledWith(DEMO_OWNER));
    expect(screen.getByText(/pact serve --base-url .* --agent-token pat_onboard1234567890/i)).toBeTruthy();
    expect(screen.getAllByText(/not serving yet/i).length).toBeGreaterThan(0);  // worker offline
  });

  it("re-checks connector health on demand so a finished setup unlocks without leaving", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.connectorHealth)
      .mockResolvedValueOnce(connectorHealthNeedsSetup())
      .mockResolvedValue(connectorHealth());

    renderOnboard();
    expect(await screen.findByText(/install the \/pact skill/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /re-check/i }));
    // Unlocks in place (no auto-redirect after an in-session change).
    await waitFor(() => expect((screen.getByRole("button", { name: /open dashboard/i }) as HTMLButtonElement).disabled).toBe(false));
    expect(screen.getByText(/Token pat_onboard12/i)).toBeTruthy();
  });

  it("lets the user view their sealed pact before agent setup is finished", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealthNeedsSetup());

    renderOnboard();
    const viewPact = await screen.findByRole("button", { name: /^view pact$/i });
    expect((viewPact as HTMLButtonElement).disabled).toBe(false);
  });

  it("lets the user confirm the local Pact API URL used by the serve command", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealthNeedsSetup());

    renderOnboard();
    const url = await screen.findByLabelText(/local pact api url/i) as HTMLInputElement;
    expect(url.value).toBe("http://127.0.0.1:8000");
    expect(screen.getByText(/pact serve --base-url http:\/\/127\.0\.0\.1:8000/i)).toBeTruthy();

    fireEvent.change(url, { target: { value: "http://localhost:9000" } });
    expect(screen.getByText(/pact serve --base-url http:\/\/localhost:9000/i)).toBeTruthy();
    expect(window.localStorage.getItem("pact.agentBaseUrl")).toBe("http://localhost:9000");
  });

  it("copies the customized serve command from the setup chat", async () => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealthNeedsSetup());

    renderOnboard();
    const url = await screen.findByLabelText(/local pact api url/i) as HTMLInputElement;
    fireEvent.change(url, { target: { value: "http://localhost:9000" } });
    fireEvent.click(screen.getByRole("button", { name: /copy serve command/i }));

    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "pact serve --base-url http://localhost:9000 --agent-token <paste your token>",
    ));
    expect(screen.getByRole("button", { name: /copied/i })).toBeTruthy();
  });

  it("labels dry-run funding as local-only in the setup chat", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue({
      ...linkStatus(), payment_method_id: null, payment_method_label: null,
      payment_method_last4: null, funding_ref: "test_funding_demo@pact.local",
    });
    vi.mocked(api.linkPreflight).mockResolvedValue({
      ...linkStatus(), payment_method_id: null, payment_method_label: null,
      payment_method_last4: null, funding_ref: "test_funding_demo@pact.local",
    });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealthNeedsSetup());

    renderOnboard();
    await screen.findByRole("region", { name: /hermes setup/i });
    expect(screen.queryByText(/test_funding/i)).toBeNull();
    expect(screen.getByText(/Local-only Link ready/i)).toBeTruthy();
    expect(screen.getByText(/No real card is connected/i)).toBeTruthy();
  });

  it("does not unlock setup when live Link is connected but missing a ready payment method", async () => {
    vi.mocked(api.runtime).mockResolvedValue(runtime(true));
    const notReadyLink: LinkStatus = {
      ...linkStatus(), ready: false, payment_method_id: null, payment_method_label: null,
      payment_method_last4: null, error: "No usable Link payment method is available",
    };
    vi.mocked(api.linkStatus).mockResolvedValue(notReadyLink);
    vi.mocked(api.linkPreflight).mockResolvedValue(notReadyLink);
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    renderOnboard();
    await screen.findByRole("region", { name: /hermes setup/i });
    expect(screen.getByText(/No usable Link payment method is available/i)).toBeTruthy();
    expect(screen.getByText(/not connected/i)).toBeTruthy();
    expect(screen.getByRole("link", { name: /install link cli/i })).toBeTruthy();
    expect((screen.getByRole("button", { name: /finish setup to open dashboard/i }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("renders every section completed (no auto-skip) in demo clock mode", async () => {
    vi.mocked(api.runtime).mockResolvedValue({ ...runtime(false), clock_mode: "demo" });
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    // Even with the agent token missing + worker offline, demo mode shows it done.
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealthNeedsSetup());

    renderOnboard();

    await screen.findByRole("region", { name: /hermes setup/i });
    expect(screen.getByText("connected")).toBeTruthy();  // Link CLI pill
    expect(screen.getByText("ready")).toBeTruthy();       // agent pill
    expect(screen.getByText(/Link CLI connected/i)).toBeTruthy();
    // The serve command is pre-filled with a token, not the empty placeholder.
    expect(screen.queryByText(/<paste your token>/i)).toBeNull();
    expect(screen.getByText(/--agent-token pat_/i)).toBeTruthy();
    // The dashboard is unlocked.
    expect((screen.getByRole("button", { name: /open dashboard/i }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("refreshes live Link with preflight before deciding setup is ready", async () => {
    vi.mocked(api.runtime).mockResolvedValue(runtime(true));
    vi.mocked(api.linkStatus).mockResolvedValue({ owner: DEMO_OWNER, connected: false, funding_ref: null, error: null });
    vi.mocked(api.linkPreflight).mockResolvedValue({
      owner: DEMO_OWNER, connected: true, ready: true, funding_ref: "pm_live_123",
      payment_method_id: "pm_live_123", payment_method_label: "Visa", payment_method_last4: "4242", error: null,
    });
    // Agent not yet connected, so the chat still renders (funding ready, agent missing).
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealthNeedsSetup());

    renderOnboard();
    await waitFor(() => expect(api.linkPreflight).toHaveBeenCalledWith(DEMO_OWNER));
    expect(screen.getByText(/Link CLI connected/i)).toBeTruthy();
    expect(screen.getByText(/Visa .*4242/i)).toBeTruthy();
    expect(screen.queryByRole("link", { name: /install link cli/i })).toBeNull();
  });
});

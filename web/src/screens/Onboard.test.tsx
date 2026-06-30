// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { Onboard } from "./Onboard";
import { api, DEMO_OWNER } from "../api";
import type { BillingProfile, ConnectorHealth, LinkStatus, Pact, SpendPolicy } from "../types";
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
      getPolicy: vi.fn(),
      setPolicy: vi.fn(),
      getBilling: vi.fn(),
      setBilling: vi.fn(),
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

function billing(): BillingProfile {
  return {
    owner: DEMO_OWNER, first_name: "Ada", last_name: "Lovelace", email: "ada@example.com",
    street: "1 Analytical Way", city: "London", state: "", postal_code: "EC1A 1AA", country: "GB",
  };
}

function spendPolicy(limit: number | null = null): SpendPolicy {
  return {
    owner: DEMO_OWNER, spend_limit_cents: limit,
    charity_allowlist: ["against_malaria_foundation"], rail: "nemoguard",
  };
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
    vi.mocked(api.getPolicy).mockResolvedValue(spendPolicy());
    vi.mocked(api.setPolicy).mockImplementation(async (_owner, limit) => spendPolicy(limit));
    vi.mocked(api.getBilling).mockResolvedValue(billing());
    vi.mocked(api.setBilling).mockImplementation(async (b) => b);
  });

  it("shows a serve command (with the real token) after minting", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.getPact).mockResolvedValue(pact());
    vi.mocked(api.mintAgentToken).mockResolvedValue({ owner: DEMO_OWNER, token: "pat_onboard1234567890" });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    renderOnboard();
    fireEvent.click(await screen.findByRole("button", { name: /generate token/i }));

    await waitFor(() => expect(api.connectorHealth).toHaveBeenCalledWith(DEMO_OWNER));
    // The copyable command is `pact serve` with the REAL token substituted (no placeholder).
    expect(screen.getByText(/pact serve --base-url .* --agent-token pat_onboard1234567890/i)).toBeTruthy();
    expect(screen.getAllByText(/not serving yet/i).length).toBeGreaterThan(0);  // worker offline
  });

  it("captures the billing profile via the form", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.getPact).mockResolvedValue(pact());
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());
    vi.mocked(api.getBilling).mockResolvedValue({ owner: DEMO_OWNER });  // empty -> form needed

    renderOnboard();
    const first = await screen.findByLabelText(/first name/i) as HTMLInputElement;
    fireEvent.change(first, { target: { value: "Grace" } });
    fireEvent.change(screen.getByLabelText(/last name/i), { target: { value: "Hopper" } });
    fireEvent.change(screen.getByLabelText(/^street$/i), { target: { value: "1 Navy Yard" } });
    fireEvent.change(screen.getByLabelText(/postal code/i), { target: { value: "20374" } });
    fireEvent.click(screen.getByRole("button", { name: /save billing/i }));

    await waitFor(() => expect(api.setBilling).toHaveBeenCalledWith(
      expect.objectContaining({ owner: DEMO_OWNER, first_name: "Grace", last_name: "Hopper",
        street: "1 Navy Yard", postal_code: "20374" }),
    ));
  });

  it("locks the dashboard until billing is captured", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.getPact).mockResolvedValue({ ...pact(), agent: "Hermes" });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());
    vi.mocked(api.getBilling).mockResolvedValue({ owner: DEMO_OWNER });  // no billing yet

    renderOnboard();
    await screen.findByRole("log", { name: /hermes setup chat/i });
    expect((screen.getByRole("button", { name: /finish setup to open dashboard/i }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("lets the user view their sealed pact before agent setup is finished", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.getPact).mockResolvedValue(pact());
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealthNeedsSetup());

    renderOnboard();
    const viewPact = await screen.findByRole("button", { name: /view pact/i });
    expect((viewPact as HTMLButtonElement).disabled).toBe(false);
  });

  it("re-checks connector health on demand so a finished setup unlocks without leaving", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.getPact).mockResolvedValue(pact());
    vi.mocked(api.connectorHealth)
      .mockResolvedValueOnce(connectorHealthNeedsSetup())
      .mockResolvedValue(connectorHealth());

    renderOnboard();
    expect(await screen.findByText(/install the \/pact skill/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /re-check/i }));
    await waitFor(() => expect(screen.getByText(/Token pat_onboard12/i)).toBeTruthy());
  });

  it("frames the spend limit as the agent's standing authorization to donate on a miss", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.getPact).mockResolvedValue({ ...pact(), agent: "Hermes" });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    renderOnboard();
    expect(await screen.findByText(/your agent handles the donation/i)).toBeTruthy();
  });

  it("presents first-run setup as an agent chat with a billing + agent step", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.getPact).mockResolvedValue({ ...pact(), agent: "Hermes" });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    renderOnboard();
    expect(await screen.findByRole("log", { name: /hermes setup chat/i })).toBeTruthy();
    expect(screen.getByText(/Link funding check/i)).toBeTruthy();
    expect(screen.getByText(/Billing details/i)).toBeTruthy();
    expect(screen.getByText(/Connect your agent/i)).toBeTruthy();
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

  it("lets the user confirm the local Pact API URL used by the serve command", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.getPact).mockResolvedValue({ ...pact(), agent: "Hermes" });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

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
    vi.mocked(api.getPact).mockResolvedValue({ ...pact(), agent: "Hermes" });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

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
    vi.mocked(api.getPact).mockResolvedValue({ ...pact(), agent: "Hermes" });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    renderOnboard();
    await screen.findByRole("log", { name: /hermes setup chat/i });
    expect(screen.queryByText(/test_funding/i)).toBeNull();
    expect(screen.getByText(/Local-only Link ready/i)).toBeTruthy();
    expect(screen.getByText(/No real card is connected/i)).toBeTruthy();
  });

  it("lets new users set the agent spend limit before the dashboard handoff", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.getPact).mockResolvedValue({ ...pact(), agent: "Hermes" });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealth());

    renderOnboard();
    const limitInput = await screen.findByRole("spinbutton", { name: /agent spend limit/i });
    fireEvent.change(limitInput, { target: { value: "15" } });
    fireEvent.click(screen.getByRole("button", { name: /save spend limit/i }));

    await waitFor(() => expect(api.setPolicy).toHaveBeenCalledWith(DEMO_OWNER, 1500));
    expect(screen.getByText(/agent may spend up to \$15\.00/i)).toBeTruthy();
    expect(screen.getByText(/NemoGuard checks every charge/i)).toBeTruthy();
  });

  it("does not unlock setup when live Link is connected but missing a ready payment method", async () => {
    vi.mocked(api.runtime).mockResolvedValue(runtime(true));
    const notReadyLink: LinkStatus = {
      ...linkStatus(), ready: false, payment_method_id: null, payment_method_label: null,
      payment_method_last4: null, error: "No usable Link payment method is available",
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
    expect((screen.getByRole("button", { name: /finish setup to open dashboard/i }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("keeps the dashboard locked until setup is ready, but lets the user view their pact", async () => {
    vi.mocked(api.linkStatus).mockResolvedValue(linkStatus());
    vi.mocked(api.getPact).mockResolvedValue({ ...pact(), agent: "Hermes" });
    vi.mocked(api.connectorHealth).mockResolvedValue(connectorHealthNeedsSetup());

    renderOnboard();
    await screen.findByRole("log", { name: /hermes setup chat/i });
    expect(screen.getByText(/install the \/pact skill/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /re-check/i })).toBeTruthy();
    expect((screen.getByRole("button", { name: /finish setup to open dashboard/i }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: /^view pact$/i }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("refreshes live Link with preflight before deciding setup is ready", async () => {
    vi.mocked(api.runtime).mockResolvedValue(runtime(true));
    vi.mocked(api.linkStatus).mockResolvedValue({ owner: DEMO_OWNER, connected: false, funding_ref: null, error: null });
    vi.mocked(api.linkPreflight).mockResolvedValue({
      owner: DEMO_OWNER, connected: true, ready: true, funding_ref: "pm_live_123",
      payment_method_id: "pm_live_123", payment_method_label: "Visa", payment_method_last4: "4242", error: null,
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

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api, DEMO_OWNER } from "./api";
import { isDesktop } from "./lib/platform";
import { RootEntry } from "./RootEntry";

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return {
    ...actual,
    api: {
      listPacts: vi.fn(),
    },
  };
});

vi.mock("./lib/platform", () => ({
  isDesktop: vi.fn(),
}));

vi.mock("./owner", () => ({
  getLocalOwner: () => DEMO_OWNER,
}));

function renderRootEntry() {
  return render(
    <MemoryRouter
      initialEntries={["/"]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Routes>
        <Route path="/" element={<RootEntry />} />
        <Route path="/create" element={<div>Create deck reached</div>} />
        <Route path="/dashboard" element={<div>Dashboard reached</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe("RootEntry", () => {
  beforeEach(() => {
    vi.mocked(isDesktop).mockReturnValue(true);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows a visible desktop launch state while it checks whether this is first run", () => {
    vi.mocked(api.listPacts).mockReturnValue(new Promise(() => {}));

    renderRootEntry();

    expect(screen.getByRole("status", { name: /opening pact/i })).toBeTruthy();
    expect(screen.getByText(/Opening the pact deck/i)).toBeTruthy();
  });

  it("sends desktop first-run owners to the create deck", async () => {
    vi.mocked(api.listPacts).mockResolvedValue([]);

    renderRootEntry();

    await waitFor(() => expect(api.listPacts).toHaveBeenCalledWith(DEMO_OWNER));
    expect(await screen.findByText("Create deck reached")).toBeTruthy();
  });

  it("sends returning desktop owners to the dashboard", async () => {
    vi.mocked(api.listPacts).mockResolvedValue([{ id: "pact_1" } as Awaited<ReturnType<typeof api.listPacts>>[number]]);

    renderRootEntry();

    expect(await screen.findByText("Dashboard reached")).toBeTruthy();
  });
});

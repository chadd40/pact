// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api } from "../api";
import { AppShell } from "./AppShell";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    api: {
      listPacts: vi.fn(),
      charities: vi.fn(),
    },
  };
});

vi.mock("../App", () => ({
  useDemo: () => ({
    bump: 0,
    busy: null,
    doSeed: vi.fn(),
    doAdvance: vi.fn(),
    doReset: vi.fn(),
  }),
}));

vi.mock("../owner", () => ({
  useLocalOwner: () => ["owner@example.com"],
}));

function renderShell() {
  return render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/dashboard" element={<div>Dashboard content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

describe("AppShell", () => {
  beforeEach(() => {
    vi.mocked(api.listPacts).mockResolvedValue([]);
    vi.mocked(api.charities).mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders the floating logo-menu button and no old sidebar chrome", async () => {
    const { container } = renderShell();

    expect(await screen.findByText("Dashboard content")).toBeTruthy();
    expect(container.querySelector(".as-side, .as-sidebar")).toBeNull();
    expect(container.querySelector(".as-topbar")).toBeNull();
    expect(container.querySelector(".as-logo")).toBeTruthy();
    expect(screen.getByRole("button", { name: /menu/i })).toBeTruthy();
  });

  it("does not expose demo state controls in the fresh app shell", async () => {
    renderShell();

    expect(await screen.findByText("Dashboard content")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /states/i })).toBeNull();
    expect(screen.queryByText(/seed demo/i)).toBeNull();
    expect(screen.queryByText(/jump to state/i)).toBeNull();
  });
});

// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppShell } from "./AppShell";

afterEach(cleanup);

// Mock useDemo so AppShell renders without a live DemoContext provider.
vi.mock("../App", () => ({
  useDemo: () => ({
    bump: 0,
    busy: null,
    doSeed: vi.fn(),
    doAdvance: vi.fn(),
    doReset: vi.fn(),
  }),
}));

// Mock the api module so no real network calls are made.
vi.mock("../api", () => ({
  DEMO_OWNER: "test@example.com",
  api: {
    listPacts: () => Promise.resolve([]),
    charities: () => Promise.resolve([]),
    profile: () => Promise.resolve(null),
  },
}));

it("renders the floating logo-menu button and no sidebar", () => {
  const { container, getByRole } = render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <AppShell />
    </MemoryRouter>
  );
  // Sidebar must be gone — `.as-side` was the real old sidebar class.
  expect(container.querySelector(".as-side, .as-sidebar")).toBeNull();
  // LogoMenu button must be present (aria-label="Pact menu" matches /menu/i).
  expect(getByRole("button", { name: /menu/i })).toBeTruthy();
});

describe("AppShell shell layout", () => {
  it("floats the logo (.as-logo) with no top bar and no sidebar", () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/dashboard"]}>
        <AppShell />
      </MemoryRouter>
    );
    expect(container.querySelector(".as-side")).toBeNull();
    // The full-width top bar is gone; the logo floats instead.
    expect(container.querySelector(".as-topbar")).toBeNull();
    expect(container.querySelector(".as-logo")).toBeTruthy();
  });
});

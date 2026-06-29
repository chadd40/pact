// @vitest-environment jsdom
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { LogoMenu } from "./LogoMenu";

afterEach(cleanup);
const setup = () => render(
  <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
    <LogoMenu />
  </MemoryRouter>
);

describe("LogoMenu", () => {
  it("uses the compact logo without a caret", () => {
    const { container } = setup();
    expect(screen.getByAltText("Pact").getAttribute("src")).toContain("compact_nav_pact.svg");
    expect(container.querySelector(".lm-navcaret")).toBeNull();
  });
  it("is closed initially and opens on click", async () => {
    setup();
    expect(screen.queryByRole("menu")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /menu/i }));
    expect(screen.getByRole("menu")).toBeTruthy();
    for (const label of ["Home", "Coach", "Charities", "Settings"]) {
      expect(screen.getByRole("menuitem", { name: label })).toBeTruthy();
    }
  });
  it("closes on Escape", async () => {
    setup();
    await userEvent.click(screen.getByRole("button", { name: /menu/i }));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
  });
});

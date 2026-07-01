// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LandingLogoMenu } from "./LandingLogoMenu";

afterEach(cleanup);

describe("LandingLogoMenu", () => {
  it("opens the landing menu with the compact logo and no caret", async () => {
    const { container } = render(<LandingLogoMenu onGoTo={vi.fn()} />);
    expect(screen.getByAltText("Pact").getAttribute("src")).toContain("compact_nav_pact.svg");
    expect(container.querySelector(".lp-navcaret")).toBeNull();
    expect(screen.queryByRole("menu")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /menu/i }));

    expect(screen.getByRole("menu")).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "Home" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "How it works" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "FAQ" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "Download Pact" })).toBeTruthy();
  });

  it("calls the requested landing target and closes", async () => {
    const onGoTo = vi.fn();
    render(<LandingLogoMenu onGoTo={onGoTo} />);

    await userEvent.click(screen.getByRole("button", { name: /menu/i }));
    await userEvent.click(screen.getByRole("menuitem", { name: "FAQ" }));

    expect(onGoTo).toHaveBeenCalledWith("faq");
    expect(screen.queryByRole("menu")).toBeNull();
  });
});

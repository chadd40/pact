// @vitest-environment jsdom
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { StatsFlyout } from "./StatsFlyout";
import type { Pact, Profile } from "../types";

afterEach(cleanup);

const profile = { current_streak: 3, best_streak: 9, kept: 3, failed: 1 } as Profile;
const pacts = [{ status: "active", stake_amount_cents: 5000 }, { status: "donated", stake_amount_cents: 4000 }] as Pact[];

describe("StatsFlyout", () => {
  it("shows the collapsed \"Stats\" label", () => {
    render(<StatsFlyout profile={profile} pacts={pacts} />);
    expect(screen.getByText("Stats")).toBeTruthy();
  });
  it("renders all five stats with labels in order", () => {
    render(<StatsFlyout profile={profile} pacts={pacts} />);
    const labels = screen.getAllByTestId("flyout-stat-label").map((n) => n.textContent);
    expect(labels).toEqual(["Current streak", "Best streak", "Win rate", "Active pacts", "Donated"]);
  });
});

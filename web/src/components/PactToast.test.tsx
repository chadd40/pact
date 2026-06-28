// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PactToast } from "./PactToast";

afterEach(cleanup);

const pact = { id: "p1", stake_amount_cents: 5000 } as any;

describe("PactToast", () => {
  it("renders nothing when no pact", () => {
    const { container } = render(<PactToast pact={null} onResolve={() => {}} />);
    expect(container.firstChild).toBeNull();
  });
  it("shows the stake and calls onResolve on click", async () => {
    const onResolve = vi.fn();
    render(<PactToast pact={pact} onResolve={onResolve} />);
    expect(screen.getByText(/\$50/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /resolve/i }));
    expect(onResolve).toHaveBeenCalledWith("p1");
  });
  it("collapses to a dot when dismissed and re-expands", async () => {
    render(<PactToast pact={pact} onResolve={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(screen.queryByText(/unresolved/i)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /action needed/i }));
    expect(screen.getByText(/unresolved/i)).toBeTruthy();
  });
});

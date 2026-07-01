// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NotificationsMenu } from "./NotificationsBell";
import type { Charity, CoachingMessage, Pact } from "../types";

afterEach(cleanup);

const pact = (over: Partial<Pact>): Pact => ({
  id: "p1", title: "Ship the landing page", stake_amount_cents: 4000,
  charity_id: "feeding-america", status: "donation_pending",
  deadline_at: "2026-06-20T00:00:00Z", verdict_at: "2026-06-25T00:00:00Z",
  ...over,
} as Pact);

const nudge = (over: Partial<CoachingMessage>): CoachingMessage => ({
  id: "m1", pact_id: "p1", direction: "outbound", trigger: "pace",
  pact_state_snapshot: {}, channel: "relay", body: "3 days left — log today's run?",
  sent_at: "2026-06-30T10:00:00Z", delivered_at: null,
  ...over,
} as CoachingMessage);

const charityById: Record<string, Charity> = {
  "feeding-america": { id: "feeding-america", name: "Feeding America" } as Charity,
};

const base = {
  charityById,
  pactById: { p1: pact({}) },
  nowMs: Date.parse("2026-06-30T12:00:00Z"),
  onResolve: () => {}, onOpenPact: () => {}, onMarkRead: () => {}, onMarkAllRead: () => {},
};

describe("NotificationsMenu", () => {
  it("badges the total of resolutions + nudges", () => {
    render(<NotificationsMenu {...base} resolutions={[pact({})]} nudges={[nudge({}), nudge({ id: "m2" })]} />);
    expect(screen.getByRole("button", { name: /3 need you/i })).toBeTruthy();
  });

  it("shows no badge and an all-caught-up empty state when nothing is pending", async () => {
    render(<NotificationsMenu {...base} resolutions={[]} nudges={[]} />);
    const bell = screen.getByRole("button", { name: /^notifications$/i });
    expect(bell.textContent).not.toMatch(/\d/);
    await userEvent.click(bell);
    expect(screen.getByText(/all caught up/i)).toBeTruthy();
  });

  it("puts resolutions on top with a Resolve action", async () => {
    const onResolve = vi.fn();
    render(<NotificationsMenu {...base} resolutions={[pact({})]} nudges={[]} onResolve={onResolve} />);
    await userEvent.click(screen.getByRole("button", { name: /1 need you/i }));
    expect(screen.getByText(/needs resolution/i)).toBeTruthy();
    expect(screen.getByText(/\$40 unresolved · Feeding America/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /^resolve$/i }));
    expect(onResolve).toHaveBeenCalledWith("p1");
  });

  it("labels a failed donation as a retry", async () => {
    render(<NotificationsMenu {...base} resolutions={[pact({ status: "donation_failed" })]} nudges={[]} />);
    await userEvent.click(screen.getByRole("button", { name: /need you/i }));
    expect(screen.getByRole("button", { name: /^retry$/i })).toBeTruthy();
  });

  it("renders coach nudges and marks one read", async () => {
    const onMarkRead = vi.fn();
    render(<NotificationsMenu {...base} resolutions={[]} nudges={[nudge({})]} onMarkRead={onMarkRead} />);
    await userEvent.click(screen.getByRole("button", { name: /need you/i }));
    expect(screen.getByText(/log today's run/i)).toBeTruthy();
    expect(screen.getByText(/Coach ·/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /mark read/i }));
    expect(onMarkRead).toHaveBeenCalledWith("m1");
  });

  it("mark all read fires only when there are nudges", async () => {
    const onMarkAllRead = vi.fn();
    const { rerender } = render(<NotificationsMenu {...base} resolutions={[pact({})]} nudges={[]} onMarkAllRead={onMarkAllRead} />);
    await userEvent.click(screen.getByRole("button", { name: /need you/i }));
    expect(screen.queryByRole("button", { name: /mark all read/i })).toBeNull();
    rerender(<NotificationsMenu {...base} resolutions={[pact({})]} nudges={[nudge({})]} onMarkAllRead={onMarkAllRead} />);
    await userEvent.click(screen.getByRole("button", { name: /mark all read/i }));
    expect(onMarkAllRead).toHaveBeenCalled();
  });
});

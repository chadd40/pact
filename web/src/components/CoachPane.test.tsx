// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CoachPane } from "./CoachPane";
import type { Pact } from "../types";

function pact(): Pact {
  return {
    id: "p1",
    owner: "demo",
    original_prompt: "",
    title: "Work out",
    goal: "Move",
    timezone: "UTC",
    deadline_at: "2026-07-01T12:00:00Z",
    target_count: 1,
    distinct_days: true,
    days_per_week: 5,
    weeks: 4,
    recommended_stake_cents: 1000,
    stake_amount_cents: 1000,
    currency: "usd",
    charity_id: "amf",
    charity_url: "",
    agent: "Hermes",
    proof_source: "photo",
    freezes_allowed: 0,
    freezes_used: 0,
    freeze_extension_hours: 0,
    rubric: {
      modality: "photo",
      require_token: false,
      must_show: [],
      reject_if: [],
      min_distinct_days: 0,
      count_target: 1,
      rest_if_injured_counts: false,
      rigor_floor: {},
    },
    status: "active",
    stake_state: "committed",
    spend_request_id: null,
    created_at: "2026-06-28T12:00:00Z",
    started_at: "2026-06-28T12:00:00Z",
    verdict_at: null,
    dispute_window_closes_at: null,
  };
}

describe("CoachPane", () => {
  afterEach(() => cleanup());

  it("uses the agent chat composer shape without the old status label", async () => {
    const onSend = vi.fn();
    render(<CoachPane pact={pact()} messages={[]} onSend={onSend} onClose={() => {}} />);

    const input = screen.getByRole("textbox", { name: /message hermes/i });
    await userEvent.type(input, "proof question");

    expect(document.activeElement).toBe(input);
    expect(screen.queryByText(/coaching this pact/i)).toBeNull();
    expect(screen.getByRole("button", { name: /add photos or files/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /send/i })).toBeTruthy();
  });

  it("opens a native attachment picker and shows selected files", async () => {
    const clickInput = vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(() => {});
    render(<CoachPane pact={pact()} messages={[]} onSend={vi.fn()} onClose={() => {}} />);

    await userEvent.click(screen.getByRole("button", { name: /add photos or files/i }));
    expect(clickInput).toHaveBeenCalled();

    const file = new File(["hello"], "proof-note.txt", { type: "text/plain" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    expect(screen.getByText("proof-note.txt")).toBeTruthy();
  });

  it("sends selected files with the coach message", async () => {
    const onSend = vi.fn();
    render(<CoachPane pact={pact()} messages={[]} onSend={onSend} onClose={() => {}} />);

    const file = new File(["hello"], "proof-note.txt", { type: "text/plain" });
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });

    await userEvent.type(screen.getByRole("textbox", { name: /message hermes/i }), "please review");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(onSend).toHaveBeenCalledWith("please review", [file]);
  });

  it("lets the user remove an accidental attachment before sending", async () => {
    const onSend = vi.fn();
    render(<CoachPane pact={pact()} messages={[]} onSend={onSend} onClose={() => {}} />);

    const keep = new File(["keep"], "keep.png", { type: "image/png" });
    const remove = new File(["remove"], "remove.png", { type: "image/png" });
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [keep, remove] } });

    await userEvent.click(screen.getByRole("button", { name: /remove remove\.png/i }));

    expect(screen.queryByText("remove.png")).toBeNull();
    expect(screen.getByText("keep.png")).toBeTruthy();

    await userEvent.type(screen.getByRole("textbox", { name: /message hermes/i }), "use this one");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(onSend).toHaveBeenCalledWith("use this one", [keep]);
  });
});

// @vitest-environment jsdom
// web/src/components/PasteWebPact.test.tsx
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PasteWebPact } from "./PasteWebPact";
import { encodeDraft, type PactDraft } from "../lib/handoff";

const DRAFT: PactDraft = {
  goal: "Read nightly", frequency: { days_per_week: 5, weeks: 4 },
  stake_amount_cents: 3000, charity_id: "against_malaria_foundation", agent: "Hermes",
};

describe("PasteWebPact", () => {
  afterEach(() => cleanup());

  it("expands, accepts a valid blob, and calls onImport", async () => {
    const onImport = vi.fn();
    render(<PasteWebPact onImport={onImport} />);
    await userEvent.click(screen.getByRole("button", { name: /paste web pact/i }));
    const box = screen.getByRole("textbox");
    await userEvent.type(box, encodeDraft(DRAFT));
    await userEvent.click(screen.getByRole("button", { name: /submit|✓|done/i }));
    expect(onImport).toHaveBeenCalledTimes(1);
    expect(onImport.mock.calls[0][0].goal).toBe("Read nightly");
  });

  it("shows an error for a bad blob and does not call onImport", async () => {
    const onImport = vi.fn();
    render(<PasteWebPact onImport={onImport} />);
    await userEvent.click(screen.getByRole("button", { name: /paste web pact/i }));
    await userEvent.type(screen.getByRole("textbox"), "not a pact");
    await userEvent.click(screen.getByRole("button", { name: /submit|✓|done/i }));
    expect(onImport).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toBeTruthy();
  });
});

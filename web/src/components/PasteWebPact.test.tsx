// @vitest-environment jsdom
// web/src/components/PasteWebPact.test.tsx
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { PasteWebPact } from "./PasteWebPact";
import { encodeDraft, type PactDraft } from "../lib/handoff";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(resolve(here, "paste-web-pact.css"), "utf8");

const DRAFT: PactDraft = {
  goal: "Read nightly", frequency: { days_per_week: 5, weeks: 4 },
  stake_amount_cents: 3000, charity_id: "against_malaria_foundation", agent: "Hermes",
};

describe("PasteWebPact", () => {
  afterEach(() => cleanup());

  it("renders the collapsed action as a bespoke clipboard handoff station", () => {
    render(<PasteWebPact onImport={() => {}} />);

    const button = screen.getByRole("button", { name: /paste web pact/i });

    expect(button.querySelector(".pwp-chip-orbit")).toBeTruthy();
    expect(button.querySelector(".pwp-chip-status")).toBeTruthy();
    expect(screen.getByText("From pact.com")).toBeTruthy();
    expect(screen.getByText("Clipboard")).toBeTruthy();
    expect(button.getAttribute("title")).toBeNull();
  });

  it("uses custom paste chrome instead of a generic button treatment", () => {
    expect(css).toContain(".pwp-chip::before");
    expect(css).toContain(".pwp-chip-orbit");
    expect(css).toContain(".pwp-chip-status");
    expect(css).toMatch(/backdrop-filter:\s*blur\(14px\)/);
    expect(css).toMatch(/box-shadow:\s*inset 0 1px 0 rgba\(255, 255, 255, 0\.74\)/);
  });

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

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

function setClipboard(readText: () => Promise<string>) {
  Object.defineProperty(navigator, "clipboard", {
    value: { readText },
    configurable: true,
    writable: true,
  });
}

describe("PasteWebPact", () => {
  afterEach(() => cleanup());

  it("renders a paste circle with an accessible label and a tooltip", () => {
    render(<PasteWebPact onImport={() => {}} />);
    const button = screen.getByRole("button", { name: /paste web pact/i });
    expect(button.className).toContain("pwp-circle");
    expect(button.querySelector(".pwp-tip")?.textContent).toContain("Paste web pact");
  });

  it("reads a valid clipboard pact, imports it, and shows the success pill", async () => {
    setClipboard(() => Promise.resolve(encodeDraft(DRAFT)));
    const onImport = vi.fn();
    render(<PasteWebPact onImport={onImport} />);
    await userEvent.click(screen.getByRole("button", { name: /paste web pact/i }));
    expect(await screen.findByText("Pact imported")).toBeTruthy();
    expect(onImport).toHaveBeenCalledTimes(1);
    expect(onImport.mock.calls[0][0].goal).toBe("Read nightly");
  });

  it("shows an inline error for a non-pact clipboard and does not import", async () => {
    setClipboard(() => Promise.resolve("not a pact"));
    const onImport = vi.fn();
    render(<PasteWebPact onImport={onImport} />);
    await userEvent.click(screen.getByRole("button", { name: /paste web pact/i }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(onImport).not.toHaveBeenCalled();
  });

  it("shows an error when the clipboard can't be read", async () => {
    setClipboard(() => Promise.reject(new Error("denied")));
    const onImport = vi.fn();
    render(<PasteWebPact onImport={onImport} />);
    await userEvent.click(screen.getByRole("button", { name: /paste web pact/i }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(onImport).not.toHaveBeenCalled();
  });

  it("styles the circle and the morphing status pill (with reduced-motion)", () => {
    expect(css).toContain(".pwp-circle");
    expect(css).toContain(".pwp-pill");
    expect(css).toContain(".pwp-pill-ok");
    expect(css).toContain(".pwp-pill-err");
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)/);
  });
});

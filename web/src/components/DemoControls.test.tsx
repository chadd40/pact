// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DemoControls } from "./DemoControls";
import { DemoContext } from "../App";
import { api } from "../api";
import type { RuntimeInfo } from "../types";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, api: { runtime: vi.fn(), tick: vi.fn() } };
});

function _runtime(clock_mode: string): RuntimeInfo {
  return {
    payment_mode: "test_link", link_mode: "dry_run", reasoning_mode: "hybrid",
    auth_mode: "local_dev", live_money_enabled: false, clock_mode,
  };
}

function _ctx(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    nowIso: null, setNow: vi.fn(), refreshNow: vi.fn(), bump: 0, signalChange: vi.fn(),
    busy: null, doSeed: vi.fn(), doAdvance: vi.fn(), doReset: vi.fn(), ...overrides,
  } as never;
}

function renderWith(ctx: unknown) {
  return render(<DemoContext.Provider value={ctx as never}><DemoControls /></DemoContext.Provider>);
}

afterEach(() => { cleanup(); vi.clearAllMocks(); });

// Fires ⌥⌘T (Option+Cmd+T). keydown bubbles from body up to the window listener.
const toggleKey = () =>
  fireEvent.keyDown(document.body, { code: "KeyT", metaKey: true, altKey: true });

it("reveals demo controls with ⌥⌘T in demo mode and drives the real endpoints", async () => {
  vi.mocked(api.runtime).mockResolvedValue(_runtime("demo"));
  vi.mocked(api.tick).mockResolvedValue({} as never);
  const ctx = _ctx();
  renderWith(ctx);

  // Hidden until the shortcut reveals it (armed once demo mode is detected).
  await waitFor(() => {
    toggleKey();
    screen.getByRole("button", { name: /\+5 days/i });
  });

  fireEvent.click(screen.getByRole("button", { name: /\+5 days/i }));
  expect((ctx as { doAdvance: ReturnType<typeof vi.fn> }).doAdvance).toHaveBeenCalledWith(5);

  fireEvent.click(screen.getByRole("button", { name: /run agent/i }));
  await waitFor(() => expect(api.tick).toHaveBeenCalled());
  expect((ctx as { signalChange: ReturnType<typeof vi.fn> }).signalChange).toHaveBeenCalled();
});

it("stays hidden by default in demo mode until ⌥⌘T, and hides again on a second press", async () => {
  vi.mocked(api.runtime).mockResolvedValue(_runtime("demo"));
  renderWith(_ctx());
  await waitFor(() => expect(api.runtime).toHaveBeenCalled());
  expect(screen.queryByText("DEMO")).toBeNull();

  await waitFor(() => {
    toggleKey();
    screen.getByText("DEMO");
  });

  toggleKey();
  expect(screen.queryByText("DEMO")).toBeNull();
});

it("is hidden when not in demo clock mode", async () => {
  vi.mocked(api.runtime).mockResolvedValue(_runtime("real"));
  renderWith(_ctx());
  await waitFor(() => expect(api.runtime).toHaveBeenCalled());
  expect(screen.queryByText("DEMO")).toBeNull();
});

it("ignores ⌥⌘T when not in demo clock mode", async () => {
  vi.mocked(api.runtime).mockResolvedValue(_runtime("real"));
  renderWith(_ctx());
  await waitFor(() => expect(api.runtime).toHaveBeenCalled());
  toggleKey();
  expect(screen.queryByText("DEMO")).toBeNull();
});

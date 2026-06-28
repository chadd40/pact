// @vitest-environment jsdom
import { describe, it, expect, afterEach } from "vitest";
import { isDesktop } from "./platform";

declare global { interface Window { __PACT_API_BASE__?: string } }

afterEach(() => { delete (window as Window).__PACT_API_BASE__; });

describe("isDesktop", () => {
  it("false when the base global is absent", () => {
    expect(isDesktop()).toBe(false);
  });
  it("true when the Rust shell injected a base url", () => {
    (window as Window).__PACT_API_BASE__ = "http://127.0.0.1:8000";
    expect(isDesktop()).toBe(true);
  });
  it("false for an empty string", () => {
    (window as Window).__PACT_API_BASE__ = "";
    expect(isDesktop()).toBe(false);
  });
});

import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(resolve(here, "app.css"), "utf8");

function ruleFor(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`, "m"));
  return match?.[1] ?? "";
}

function decl(rule: string, name: string): string {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = rule.match(new RegExp(`${escaped}\\s*:\\s*([^;]+);`));
  return match?.[1].trim() ?? "";
}

function px(value: string): number {
  return Number(value.match(/-?\d+(?:\.\d+)?/)?.[0] ?? NaN);
}

describe("app shell layout CSS", () => {
  it("uses the same content origin below the floating logo on home and secondary pages", () => {
    expect(decl(ruleFor(".as-root"), "--app-page-x")).toBe("40px");
    expect(decl(ruleFor(".as-root"), "--app-content-top")).toBe("116px");
    expect(decl(ruleFor(".home-head"), "padding")).toBe("var(--app-content-top) var(--app-page-x) 0");
    expect(decl(ruleFor(".pg"), "padding")).toBe("var(--app-content-top) var(--app-page-x) 60px");
  });

  it("keeps the dashboard header compact once it clears the logo", () => {
    const headline = ruleFor(".home-headline");
    const shelfLabel = ruleFor(".home-shelf-label");

    expect(px(decl(headline, "margin-top"))).toBeLessThanOrEqual(1);
    expect(Number(decl(headline, "line-height"))).toBeLessThanOrEqual(1.04);
    expect(px(decl(shelfLabel, "top"))).toBeLessThanOrEqual(10);
    expect(decl(shelfLabel, "left")).toBe("var(--app-page-x)");
  });

  it("removes the legacy Stats flyout from the app chrome", () => {
    expect(css).not.toMatch(/\.flyout(?:[\s:{.#])/);
    expect(existsSync(resolve(here, "../components/StatsFlyout.tsx"))).toBe(false);
  });

  it("removes the legacy demo States menu from the app chrome", () => {
    const appShell = readFileSync(resolve(here, "../components/AppShell.tsx"), "utf8");

    expect(css).not.toContain(".as-states");
    expect(appShell).not.toContain("VITE_SHOW_DEMO_STATES");
    expect(appShell).not.toContain("States");
  });
});

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const createSource = readFileSync(resolve(here, "Create.tsx"), "utf8");
const createCss = readFileSync(resolve(here, "create.css"), "utf8");
const componentCss = readFileSync(resolve(here, "../components.css"), "utf8");

function mediaBlock(query: string): string {
  const start = createCss.indexOf(`@media ${query}`);
  if (start === -1) return "";
  const next = createCss.indexOf("\n@media ", start + 1);
  return createCss.slice(start, next === -1 ? undefined : next);
}

function ruleFor(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = createCss.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`, "m"));
  return match?.[1] ?? "";
}

function decl(rule: string, name: string): string {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = rule.match(new RegExp(`${escaped}\\s*:\\s*([^;]+);`));
  return match?.[1].trim() ?? "";
}

describe("create flow chrome", () => {
  it("recedes unchosen cards after a card is selected", () => {
    expect(createSource).toContain("const isLeftTrail = off < 0;");
    expect(createSource).toContain('filter: "blur(16px) saturate(0.55)"');
    expect(createSource).toContain('pointerEvents: "none"');
  });

  it("keeps cause names in a custom tooltip instead of native browser chrome", () => {
    expect(createSource).toContain("<Tooltip key={c.id} label={c.name}>");
    expect(createSource).toContain("aria-label={c.name}");
    expect(createSource).not.toMatch(/title=\{c\.name\}/);
    expect(componentCss).toContain(".pc-tooltip-bubble");
    expect(componentCss).toContain("background: #11100c");
  });

  it("hides create-page brand chrome on the small-screen fallback", () => {
    const smallScreenCss = mediaBlock("(max-width: 720px)");

    expect(smallScreenCss).toContain(".pc-brand");
    expect(smallScreenCss).toContain(".pc-paste-slot");
    expect(smallScreenCss).toContain(".pc-root .lp-nav");
    expect(smallScreenCss).toMatch(/display:\s*none;/);
  });

  it("keeps the signing state in the same right-side lane as the setup chat", () => {
    expect(createSource).toContain('className="pc-sealing-card"');
    expect(createSource).toContain("Creating your pact");
    expect(createSource).toContain("Preparing setup chat");

    const sending = ruleFor(".pc-sending");
    const sealingCard = ruleFor(".pc-sealing-card");
    const setupCard = ruleFor(".pc-msg-setup .card");

    expect(decl(sending, "width")).toBe("452px");
    expect(decl(sending, "left")).toBe("582px");
    expect(decl(sealingCard, "border-radius")).toBe("18px");
    expect(decl(sealingCard, "box-shadow")).toContain("0 26px 60px");
    expect(decl(setupCard, "width")).toBe("452px");
  });
});

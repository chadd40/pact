import type { Pact } from "../types";

export type DotLevel = "green" | "amber" | "red";

export function statusDot(pact: Pick<Pact, "target_count" | "progress">): DotLevel {
  const prog = pact.progress;
  if (!prog) return "green";
  const need = Math.max(0, prog.target - prog.valid_count);
  if (need === 0) return "green";
  if (need > prog.days_left) return "red";
  if (prog.behind || need === prog.days_left) return "amber";
  return "green";
}

import type { Pact, PactStatus } from "./types";

export function dollars(cents: number): string {
  const v = cents / 100;
  return v % 1 === 0 ? `$${v.toFixed(0)}` : `$${v.toFixed(2)}`;
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

// Status → chip class + readable label.
export function statusChip(status: PactStatus): { cls: string; label: string } {
  switch (status) {
    // needs_review: proof is under review and NO money has moved. Deliberately a
    // neutral chip, distinct from the gold "active" and the red "failed", so the
    // ledger reads honestly while the verdict is still suspended.
    case "needs_review":
      return { cls: "chip-review", label: "Under review" };
    case "awaiting_stake":
      return { cls: "chip-review", label: "Awaiting stake" };
    case "active":
    case "evaluating":
    case "donation_pending":
      return { cls: "chip-active", label: status === "active" ? "Active" : status.replace(/_/g, " ") };
    case "succeeded":
    case "canceled_release":
      return { cls: "chip-kept", label: "Kept" };
    case "failed":
    case "donated":
    case "donation_complete":
    case "donation_failed":
    case "donation_declined":
    case "canceled_forfeit":
      return {
        cls: "chip-failed",
        label:
          status === "donation_complete"
            ? "Failed · donated ✓"
            : status === "donated"
              ? "Failed · donated"
              : "Failed",
      };
    default:
      return { cls: "chip-draft", label: "Draft" };
  }
}

export const TERMINAL: PactStatus[] = [
  "succeeded",
  "failed",
  "donated",
  "donation_complete",
  "donation_failed",
  "donation_declined",
  "canceled_forfeit",
  "canceled_release",
];

export function isTerminal(status: PactStatus): boolean {
  return TERMINAL.includes(status);
}

export function succeeded(status: PactStatus): boolean {
  return status === "succeeded" || status === "canceled_release";
}

// Countdown breakdown relative to `nowMs`. Returns null if past.
export function countdown(
  deadlineIso: string,
  nowMs: number
): { days: number; hours: number; minutes: number; seconds: number; past: boolean } {
  const target = new Date(deadlineIso).getTime();
  let diff = Math.floor((target - nowMs) / 1000);
  const past = diff <= 0;
  diff = Math.max(0, diff);
  const days = Math.floor(diff / 86400);
  const hours = Math.floor((diff % 86400) / 3600);
  const minutes = Math.floor((diff % 3600) / 60);
  const seconds = diff % 60;
  return { days, hours, minutes, seconds, past };
}

// "2 of 5 across distinct days, 3 days left, need 3" — pace narrative.
export function pace(pact: Pact, validCount: number, nowMs: number): string {
  const c = countdown(pact.deadline_at, nowMs);
  const need = Math.max(0, pact.target_count - validCount);
  const left = c.past ? "past deadline" : `${c.days} day${c.days === 1 ? "" : "s"} left`;
  if (need === 0) return `${validCount} of ${pact.target_count} across distinct days — target met`;
  return `${validCount} of ${pact.target_count} across distinct days · ${left} · need ${need} more`;
}

// A short deterministic nonce hint label for the proof token.
export function tokenLine(token: string): string {
  return token;
}

// A stable 3-digit "No." for a pact card from its id (cosmetic ledger flourish).
export function pactNo(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return String((h % 900) + 100);
}

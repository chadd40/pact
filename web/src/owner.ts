import { useCallback, useEffect, useState } from "react";
import { DEMO_OWNER } from "./api";

const OWNER_KEY = "pact.localOwner";
const OWNER_EVENT = "pact-owner-change";
const DISPLAY_KEY = "pact.displayName";
const DISPLAY_EVENT = "pact-display-change";

// Legacy owner values written by older builds. They look like real account ids
// but should fall back to the current default rather than persist (e.g. the
// stale "demo@pacts.local" — note the extra 's' — some early builds wrote).
const STALE_OWNERS = new Set(["demo@pacts.local"]);

function cleanOwner(owner: string | null | undefined): string {
  const trimmed = (owner ?? "").trim();
  if (!trimmed || STALE_OWNERS.has(trimmed.toLowerCase())) return DEMO_OWNER;
  return trimmed;
}

export function getLocalOwner(): string {
  if (typeof window === "undefined") return DEMO_OWNER;
  try {
    return cleanOwner(window.localStorage.getItem(OWNER_KEY));
  } catch {
    return DEMO_OWNER;
  }
}

export function setLocalOwner(owner: string): string {
  const next = cleanOwner(owner);
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(OWNER_KEY, next);
      window.dispatchEvent(new Event(OWNER_EVENT));
    } catch {
      /* localStorage may be blocked */
    }
  }
  return next;
}

export function useLocalOwner(): [string, (owner: string) => void] {
  const [owner, setOwnerState] = useState(() => getLocalOwner());

  useEffect(() => {
    const refresh = () => setOwnerState(getLocalOwner());
    window.addEventListener("storage", refresh);
    window.addEventListener(OWNER_EVENT, refresh);
    return () => {
      window.removeEventListener("storage", refresh);
      window.removeEventListener(OWNER_EVENT, refresh);
    };
  }, []);

  const update = useCallback((nextOwner: string) => {
    setOwnerState(setLocalOwner(nextOwner));
  }, []);

  return [owner, update];
}

// The owner's display name — what shows as their identity across Pact. Stored
// separately from the account id (the email) so the id stays the scoping key
// (pacts, funding, agent token, donor email) while the human sees their name.
// Falls back to "" so callers can layer their own fallback (billing name, then
// the account id).
export function getDisplayName(): string {
  if (typeof window === "undefined") return "";
  try {
    return (window.localStorage.getItem(DISPLAY_KEY) ?? "").trim();
  } catch {
    return "";
  }
}

export function setDisplayName(name: string): string {
  const next = name.trim();
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(DISPLAY_KEY, next);
      window.dispatchEvent(new Event(DISPLAY_EVENT));
    } catch {
      /* localStorage may be blocked */
    }
  }
  return next;
}

export function useLocalDisplayName(): [string, (name: string) => void] {
  const [name, setNameState] = useState(() => getDisplayName());

  useEffect(() => {
    const refresh = () => setNameState(getDisplayName());
    window.addEventListener("storage", refresh);
    window.addEventListener(DISPLAY_EVENT, refresh);
    return () => {
      window.removeEventListener("storage", refresh);
      window.removeEventListener(DISPLAY_EVENT, refresh);
    };
  }, []);

  const update = useCallback((next: string) => {
    setNameState(setDisplayName(next));
  }, []);

  return [name, update];
}

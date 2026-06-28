import { useCallback, useEffect, useState } from "react";
import { DEMO_OWNER } from "./api";

const OWNER_KEY = "pact.localOwner";
const OWNER_EVENT = "pact-owner-change";

function cleanOwner(owner: string | null | undefined): string {
  return (owner ?? "").trim() || DEMO_OWNER;
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

import { createContext, useContext } from "react";
import type { Charity, Pact } from "./types";

// Shared app-data, provided once by AppShell so the in-app screens don't each
// re-fetch the same lists: `pacts` (refreshed on the demo `bump` signal) is read
// by the sidebar nag, Home carousel/ledger, and Coach; `charities` is fetched
// once and read by Home, PactDetail, and the Charities page.
export interface AppData {
  pacts: Pact[];
  pactsLoaded: boolean;
  charities: Charity[];
  charityById: Record<string, Charity>;
}

export const AppDataContext = createContext<AppData | null>(null);

export const useAppData = (): AppData => {
  const ctx = useContext(AppDataContext);
  if (!ctx) throw new Error("useAppData outside AppShell");
  return ctx;
};

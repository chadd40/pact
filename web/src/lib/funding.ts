import type { LinkStatus } from "../types";

export function isSyntheticFundingRef(ref?: string | null): boolean {
  return !!ref && /^(test_|dryrun_|link_pm_test)/i.test(ref);
}

export function fundingIsLocalOnly(link: LinkStatus | null, liveMoneyEnabled: boolean): boolean {
  return !!link?.connected && !liveMoneyEnabled;
}

export function fundingDisplay(link: LinkStatus | null, liveMoneyEnabled = true): string | null {
  if (!link?.connected) return null;
  if (fundingIsLocalOnly(link, liveMoneyEnabled)) return "Local-only Link ready";
  if (link.payment_method_last4) {
    return `${link.payment_method_label ?? "Card"} •••• ${link.payment_method_last4}`;
  }
  if (link.funding_ref && !isSyntheticFundingRef(link.funding_ref)) return link.funding_ref;
  return "Link connector ready";
}

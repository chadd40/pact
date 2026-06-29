import type { ReactNode } from "react";

export function Tooltip({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <span className="pc-tooltip">
      {children}
      <span className="pc-tooltip-bubble" role="tooltip">{label}</span>
    </span>
  );
}

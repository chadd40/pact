// A pure SVG progress ring. Renders pct (0..100) with an optional center label.
interface Props {
  pct: number;
  size?: number;
  stroke?: number;
  label?: string;
  sub?: string;
  tone?: "gold" | "green" | "muted";
}

const TONE: Record<string, string> = {
  gold: "var(--pc-gold)",
  green: "var(--pc-green)",
  muted: "var(--pc-on-card-faint)",
};

export function ProgressRing({ pct, size = 132, stroke = 10, label, sub, tone = "gold" }: Props) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(100, pct));
  const dash = (clamped / 100) * c;
  return (
    <div className="ring-wrap" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="ring-svg" aria-hidden="true">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke="var(--pc-card-line-2)"
          strokeWidth={stroke}
          fill="none"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={TONE[tone]}
          strokeWidth={stroke}
          fill="none"
          strokeDasharray={`${dash} ${c - dash}`}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: "stroke-dasharray .6s cubic-bezier(.2,.7,.2,1)" }}
        />
      </svg>
      {(label != null || sub != null) && (
        <div className="ring-center">
          {label != null && <div className="ring-label">{label}</div>}
          {sub != null && <div className="ring-sub">{sub}</div>}
        </div>
      )}
    </div>
  );
}

interface Props {
  kept: boolean;
  // The line stamped across the seal's center, e.g. "$0 MOVED" / "$20 → CHARITY".
  centerLine: string;
  // Words that ring the seal in monospace.
  ringText?: string;
}

/**
 * The signature moment: a circular wax-seal stamp that "presses in".
 * Kept → kept-green "SUCCEEDED"; failed → stake-red "FAILED".
 * Rendered as inline SVG so the ring text follows a real circular path.
 */
export function WaxSeal({ kept, centerLine, ringText }: Props) {
  const color = kept ? "var(--kept-green)" : "var(--stake-red)";
  const headline = kept ? "SUCCEEDED" : "FAILED";
  const ring =
    ringText ??
    (kept
      ? "· BINDING AGREEMENT · KEPT IN FULL · PACT · VERIFIED · "
      : "· BINDING AGREEMENT · FORFEIT · PACT · STAKE MOVED · ");

  return (
    // Press-in driven by a CSS keyframe (runs reliably on mount, no JS animation
    // controller to stall). See .wax-seal-wrap in components.css.
    <div className="wax-seal-wrap">
      <svg viewBox="0 0 320 320" className="wax-seal" style={{ color }}>
        <defs>
          <path
            id="sealRing"
            d="M160,160 m-120,0 a120,120 0 1,1 240,0 a120,120 0 1,1 -240,0"
          />
          <radialGradient id="sealGrad" cx="40%" cy="34%" r="78%">
            <stop offset="0%" stopColor={kept ? "#3c7a69" : "#9a3b3b"} />
            <stop offset="62%" stopColor={kept ? "#2f5d4f" : "#7c2d2d"} />
            <stop offset="100%" stopColor={kept ? "#234539" : "#5e1d1d"} />
          </radialGradient>
          {/* sRGB interpolation keeps the wax saturated; gentle displacement only. */}
          <filter id="sealRough" colorInterpolationFilters="sRGB">
            <feTurbulence type="fractalNoise" baseFrequency="0.012 0.012" numOctaves="3" result="n" />
            <feDisplacementMap in="SourceGraphic" in2="n" scale="4" />
          </filter>
        </defs>

        {/* solid base so the wax reads rich even before the textured layer */}
        <circle cx="160" cy="160" r="142" fill={kept ? "#2f5d4f" : "#7c2d2d"} />

        {/* wax body (textured) */}
        <g filter="url(#sealRough)">
          <circle cx="160" cy="160" r="142" fill="url(#sealGrad)" />
          <circle
            cx="160"
            cy="160"
            r="142"
            fill="none"
            stroke="rgba(255,255,255,0.12)"
            strokeWidth="2"
          />
        </g>

        {/* scalloped/notched outer edge for a pressed-wax feel */}
        <circle
          cx="160"
          cy="160"
          r="135"
          fill="none"
          stroke="rgba(0,0,0,0.18)"
          strokeWidth="1.5"
          strokeDasharray="2 6"
        />

        {/* engraved rings */}
        <circle cx="160" cy="160" r="120" fill="none" stroke="rgba(244,239,230,0.55)" strokeWidth="1.5" />
        <circle cx="160" cy="160" r="86" fill="none" stroke="rgba(244,239,230,0.35)" strokeWidth="1" />

        {/* ring of monospace text */}
        <text
          fill="rgba(244,239,230,0.85)"
          fontSize="13"
          fontFamily="'JetBrains Mono', monospace"
          letterSpacing="2.5"
          fontWeight="600"
        >
          <textPath href="#sealRing" startOffset="0%">
            {ring.repeat(2)}
          </textPath>
        </text>

        {/* center headline */}
        <text
          x="160"
          y="146"
          textAnchor="middle"
          fill="#f4efe6"
          fontFamily="'Fraunces', serif"
          fontSize="40"
          fontWeight="700"
          letterSpacing="1"
        >
          {headline}
        </text>

        {/* divider tick */}
        <line x1="120" y1="166" x2="200" y2="166" stroke="rgba(244,239,230,0.5)" strokeWidth="1" />

        {/* center money line */}
        <text
          x="160"
          y="196"
          textAnchor="middle"
          fill="#f4efe6"
          fontFamily="'JetBrains Mono', monospace"
          fontSize="19"
          fontWeight="600"
          letterSpacing="1.5"
        >
          {centerLine}
        </text>
      </svg>
    </div>
  );
}

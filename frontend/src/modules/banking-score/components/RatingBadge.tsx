import { Tone, toneVar } from "@/shared/lib/bands";

// Derive a semantic tone from any SDQ rating tier (green → blue → amber → red),
// robust to +/- variants (SDQ-AA-, SDQ-A+, SDQ-BBB-, …).
function tierTone(tier: string): Tone {
  const g = tier.replace(/^SDQ-/, "").replace(/[+-]/g, "").toUpperCase();
  if (g.startsWith("AAA") || g.startsWith("AA")) return "ok";
  if (g === "A") return "accent";
  if (g.startsWith("BBB") || g.startsWith("BB")) return "warn";
  return "alert"; // B, CCC, CC, C, D
}

interface Props {
  tier: string;
  size?: "sm" | "md" | "lg";
}

export function RatingBadge({ tier, size = "md" }: Props) {
  const color = toneVar(tierTone(tier));

  const sizeClasses = {
    sm: "px-2 py-0.5 text-xs",
    md: "px-3 py-1 text-sm",
    lg: "px-4 py-1.5 text-base",
  };

  return (
    <span
      className={`inline-flex items-center font-bold rounded-full text-white mono ${sizeClasses[size]}`}
      style={{ backgroundColor: color }}
    >
      {tier}
    </span>
  );
}

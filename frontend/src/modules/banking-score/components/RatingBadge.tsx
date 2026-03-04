const TIER_COLORS: Record<string, string> = {
  "SDQ-AAA": "#047857",
  "SDQ-AA+": "#059669",
  "SDQ-AA": "#10B981",
  "SDQ-A+": "#3B82F6",
  "SDQ-A": "#2563EB",
  "SDQ-BBB": "#F59E0B",
  "SDQ-BB": "#D97706",
  "SDQ-B": "#EA580C",
  "SDQ-CCC": "#DC2626",
  "SDQ-D": "#991B1B",
};

interface Props {
  tier: string;
  size?: "sm" | "md" | "lg";
}

export function RatingBadge({ tier, size = "md" }: Props) {
  const color = TIER_COLORS[tier] ?? "#718096";

  const sizeClasses = {
    sm: "px-2 py-0.5 text-xs",
    md: "px-3 py-1 text-sm",
    lg: "px-4 py-1.5 text-base",
  };

  return (
    <span
      className={`inline-flex items-center font-bold rounded-full text-white ${sizeClasses[size]}`}
      style={{ backgroundColor: color }}
    >
      {tier}
    </span>
  );
}

// Index bands (0-100) — shared semantics for every axis.
// Tone maps to the semantic token pairs (ok/accent/warn/alert).

export type Tone = "ok" | "accent" | "warn" | "alert" | "muted";

export interface Band {
  label: string;
  tone: Tone;
}

/** Standard index band (higher = stronger). */
export function bandFor(score: number | null | undefined): Band {
  if (score == null) return { label: "Sin dato", tone: "muted" };
  if (score >= 85) return { label: "Fuerte", tone: "ok" };
  if (score >= 70) return { label: "Sólido", tone: "accent" };
  if (score >= 55) return { label: "Vigilar", tone: "warn" };
  return { label: "Débil", tone: "alert" };
}

/** Risk-axis band (higher score = lower risk). */
export function riskBandFor(score: number | null | undefined): Band {
  if (score == null) return { label: "Sin dato", tone: "muted" };
  if (score >= 80) return { label: "Riesgo bajo", tone: "ok" };
  if (score >= 60) return { label: "Riesgo moderado", tone: "accent" };
  if (score >= 40) return { label: "Riesgo elevado", tone: "warn" };
  return { label: "Riesgo alto", tone: "alert" };
}

/** Tailwind classes (token-based) for a tone's soft badge. */
export function toneBadgeClass(tone: Tone): string {
  switch (tone) {
    case "ok":
      return "bg-ok-soft text-ok";
    case "accent":
      return "bg-accent-soft text-accent-ink";
    case "warn":
      return "bg-warn-soft text-warn";
    case "alert":
      return "bg-alert-soft text-alert";
    default:
      return "bg-surface2 text-muted";
  }
}

/** CSS var for a tone (for SVG strokes / inline fills). */
export function toneVar(tone: Tone): string {
  switch (tone) {
    case "ok":
      return "var(--ok)";
    case "accent":
      return "var(--accent)";
    case "warn":
      return "var(--warn)";
    case "alert":
      return "var(--alert)";
    default:
      return "var(--muted)";
  }
}

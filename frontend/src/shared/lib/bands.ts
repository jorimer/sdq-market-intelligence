// Index bands (0-100) — shared semantics for every axis.
// Tone maps to the semantic token pairs (ok/accent/warn/alert).

export type Tone = "ok" | "accent" | "warn" | "alert" | "muted";

export interface Band {
  label: string;
  tone: Tone;
}

/** i18n translator (key → text). Optional so non-migrated callers keep Spanish. */
type Translator = (key: string) => string;
const lbl = (t: Translator | undefined, key: string, es: string) => (t ? t(key) : es);

/** Standard index band (higher = stronger). Pass `t` to localize the label. */
export function bandFor(score: number | null | undefined, t?: Translator): Band {
  if (score == null) return { label: lbl(t, "bands.noData", "Sin dato"), tone: "muted" };
  if (score >= 85) return { label: lbl(t, "bands.strong", "Fuerte"), tone: "ok" };
  if (score >= 70) return { label: lbl(t, "bands.solid", "Sólido"), tone: "accent" };
  if (score >= 55) return { label: lbl(t, "bands.watch", "Vigilar"), tone: "warn" };
  return { label: lbl(t, "bands.weak", "Débil"), tone: "alert" };
}

/** Risk-axis band (higher score = lower risk). Pass `t` to localize the label. */
export function riskBandFor(score: number | null | undefined, t?: Translator): Band {
  if (score == null) return { label: lbl(t, "bands.noData", "Sin dato"), tone: "muted" };
  if (score >= 80) return { label: lbl(t, "bands.riskLow", "Riesgo bajo"), tone: "ok" };
  if (score >= 60) return { label: lbl(t, "bands.riskModerate", "Riesgo moderado"), tone: "accent" };
  if (score >= 40) return { label: lbl(t, "bands.riskElevated", "Riesgo elevado"), tone: "warn" };
  return { label: lbl(t, "bands.riskHigh", "Riesgo alto"), tone: "alert" };
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

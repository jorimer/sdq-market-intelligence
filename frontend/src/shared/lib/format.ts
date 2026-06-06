// Number / value formatting — always tabular-friendly.

export function fmtNum(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString("es-DO", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtScore(value: number | null | undefined): string {
  return fmtNum(value, 1);
}

export function fmtPct(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${fmtNum(value, digits)}%`;
}

export function fmtDelta(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${fmtNum(value, digits)}`;
}

export function deltaTone(value: number | null | undefined): "ok" | "alert" | "muted" {
  if (value == null || value === 0) return "muted";
  return value > 0 ? "ok" : "alert";
}

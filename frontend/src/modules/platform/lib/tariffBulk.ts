import type { CatalogSku } from "../billingApi";

/* ── Edición masiva del tarifario ─────────────────────────────────
 * Lógica PURA del editor (testeable sin UI): borrador precargado con los
 * precios vigentes y cómputo del diff (solo se publica lo MODIFICADO). */

/** Borrador: sku → intervalo → texto del input (monto). */
export type TariffDraft = Record<string, Record<string, string>>;

export interface CellChange {
  sku: string;
  label: string;
  interval: string;
  /** Monto vigente ("450.00") o null si el SKU no tiene precio aún. */
  current: string | null;
  /** Monto nuevo a publicar (normalizado, 2 decimales). */
  next: string;
}

/** Normaliza un monto de input a "1234.56"; null si no es un número > 0. */
export function normalizeAmount(raw: string): string | null {
  const cleaned = raw.trim().replace(/,/g, "");
  if (!cleaned) return null;
  const n = Number(cleaned);
  if (!Number.isFinite(n) || n <= 0) return null;
  return n.toFixed(2);
}

/** Borrador inicial: cada celda precargada con el monto vigente (o vacía). */
export function initialDraft(skus: CatalogSku[]): TariffDraft {
  const draft: TariffDraft = {};
  for (const s of skus) {
    draft[s.sku] = {};
    for (const iv of s.intervals) {
      draft[s.sku][iv] = s.prices[iv]?.amount ?? "";
    }
  }
  return draft;
}

/** Diff borrador vs vigente: celdas con monto VÁLIDO y DISTINTO del actual.
 * Una celda vacía o inválida nunca publica (no hay "borrar precio" por lote —
 * retirar una tarifa es una acción explícita del histórico). */
export function computeChanges(skus: CatalogSku[], draft: TariffDraft): CellChange[] {
  const out: CellChange[] = [];
  for (const s of skus) {
    for (const iv of s.intervals) {
      const next = normalizeAmount(draft[s.sku]?.[iv] ?? "");
      if (next == null) continue;
      const current = s.prices[iv]?.amount ?? null;
      if (current != null && Number(current) === Number(next)) continue;
      out.push({ sku: s.sku, label: s.label, interval: iv, current, next });
    }
  }
  return out;
}

import client from "@/shared/api/client";
import type { AiInsight } from "@/shared/ui/insight-types";

export const PENSION_AUDIENCES = ["inversionista", "regulador", "afiliado", "gobierno"] as const;

/** One AFP's latest rentabilidad observation. */
export interface AfpRentabilidad {
  slug: string;
  name: string;
  value: number;
  unit: string | null;
}

/** Per-AFP rentabilidad dispersion (latest period). */
export interface AfpDispersion {
  period: string | null;
  ranking: AfpRentabilidad[];
  leader: AfpRentabilidad | null;
  laggard: AfpRentabilidad | null;
  spread: number | null;
  average: number | null;
  unit: string;
}

/** National pension pulse (SIPEN). `headline` keys are namespaced series codes. */
export interface PensionPulse {
  period: string | null;
  headline: Record<string, number | null>;
  afp_rentabilidad: AfpDispersion;
  entity_count: number;
  source: string;
  model_version: string;
}

export async function getPensionPulse(): Promise<PensionPulse> {
  const { data } = await client.get("/pension-intel/pulse");
  return data;
}

/** Contextual AI insight for the pension system, oriented by audience. */
export async function getPensionInsight(
  audience: string = PENSION_AUDIENCES[0],
  deep = false,
): Promise<AiInsight | null> {
  const { data } = await client.get("/pension-intel/insight", {
    params: { audience, ...(deep ? { deep: true } : {}) },
  });
  return (data.ai_insight as AiInsight | null) ?? null;
}

/** One AFP row in the ISA ranking (relative, partial score; bands deferred). */
export interface PensionRankRow {
  rank: number | null;
  slug: string;
  name: string;
  overall_score: number | null;
  band: string | null;
  coverage: number | null;
  period: string | null;
}

export async function getPensionRankings(): Promise<{
  rankings: PensionRankRow[];
  count: number;
  scale: string;
}> {
  const { data } = await client.get("/pension-intel/rankings");
  return data;
}

/** One ISA dimension in an AFP's breakdown. */
export interface PensionDimension {
  key: string;
  label: string;
  weight: number;
  direction: "higher" | "lower";
  provenance: string; // "real" | "brecha"
  present: boolean;
  raw: number | null;
  score: number | null;
  // Retorno ajustado por riesgo (Diferido B): solo la dimensión `riesgo` los trae, y solo
  // si hay serie NAV + TPM. Presentación — NO alteran el score (que es la σ). Sharpe =
  // (retorno anualizado − TPM promedio de la ventana) / σ.
  sharpe?: number | null;
  annual_return_pct?: number | null;
  risk_free_pct?: number | null;
  vol_window_months?: number | null;
}

export interface PensionDetail {
  found: boolean;
  slug: string;
  name: string;
  period: string | null;
  overall_score: number | null;
  band: string | null;
  coverage: number | null;
  dimensions: PensionDimension[];
  model_version: string;
}

export async function getPensionEntityDetail(slug: string): Promise<PensionDetail> {
  const { data } = await client.get(`/pension-intel/${slug}/detail`);
  return data;
}

export async function getPensionEntityInsight(
  slug: string,
  audience: string = PENSION_AUDIENCES[0],
  deep = false,
): Promise<AiInsight | null> {
  const { data } = await client.get(`/pension-intel/entity-insight/${slug}`, {
    params: { audience, ...(deep ? { deep: true } : {}) },
  });
  return (data.ai_insight as AiInsight | null) ?? null;
}

export interface PensionEntityRow {
  slug: string;
  name: string;
  afp_code: string | null;
  is_active: boolean;
}

export async function getPensionEntities(): Promise<PensionEntityRow[]> {
  const { data } = await client.get("/pension-intel/entities");
  return (data.entities as PensionEntityRow[]) ?? [];
}

/** Manual upload of one AFP's estados financieros (PDF/XLSX) → ingest + recompute ISA. */
export async function uploadPensionFinancials(
  afpSlug: string,
  file: File,
): Promise<{ ok: boolean; afp: string; period: string; patrimonio: number | null; activos_totales: number | null }> {
  const form = new FormData();
  form.append("afp_slug", afpSlug);
  form.append("file", file);
  const { data } = await client.post("/pension-intel/financials/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

/** One row of the funds' investment portfolio (Cuadro 6.1): an issuer or a sub-sector
 * subtotal. `is_subtotal` rows are group headers (amount = sum of their children). */
export interface PensionHolding {
  sub_sector: string | null;
  issuer: string;
  issuer_slug: string;
  amount: number | null;
  pct: number | null;
  is_subtotal: boolean;
  macro_class: string | null; // "deuda_publica" | "bcrd" | null
  bank_entity_slug: string | null;
}

export interface PensionCartera {
  found: boolean;
  fund: string;
  period?: string | null;
  total?: number;
  summary?: {
    public_debt_amount: number;
    public_debt_pct: number | null;
    bcrd_amount: number;
    bcrd_pct: number | null;
    issuer_count: number;
  };
  holdings: PensionHolding[];
}

/** Portfolio composition by issuer (SIPEN bulletin Cuadro 6.1). Latest period by default. */
export async function getPensionCartera(period?: string, fund = "cci"): Promise<PensionCartera> {
  const { data } = await client.get("/pension-intel/cartera", {
    params: { fund, ...(period ? { period } : {}) },
  });
  return data;
}

/** Contextual AI insight over the portfolio composition, oriented by audience. */
export async function getPensionCarteraInsight(
  audience: string = PENSION_AUDIENCES[0],
  deep = false,
): Promise<AiInsight | null> {
  const { data } = await client.get("/pension-intel/cartera/insight", {
    params: { audience, ...(deep ? { deep: true } : {}) },
  });
  return (data.ai_insight as AiInsight | null) ?? null;
}

// ── Drill-down por indicador (estilo banca: detalle + tendencia + pares + insight IA) ──
export interface PensionTrendPoint { period: string; value: number }

/** System-indicator drill-down: level + full trend + its own AI insight. */
export interface PensionIndicatorDetail {
  found: boolean;
  code: string;
  label: string;
  unit: string | null;
  latest: { value: number; period: string };
  trend: PensionTrendPoint[];
  ai_insight: AiInsight | null;
}

export async function getPensionIndicator(
  code: string, withAi: boolean, audience: string, deep = false,
): Promise<PensionIndicatorDetail> {
  const { data } = await client.get("/pension-intel/indicator", {
    params: { code, with_ai: withAi, audience, ...(deep ? { deep: true } : {}) },
  });
  return data;
}

export interface PensionDimPeer { afp: string; raw: number | null; score: number | null }

/** AFP-dimension drill-down: value + score + peer panel + trend + its own AI insight. */
export interface PensionDimensionDetail {
  found: boolean;
  slug: string;
  afp: string;
  period: string | null;
  dimension: PensionDimension;
  peers: PensionDimPeer[];
  trend: PensionTrendPoint[];
  ai_insight: AiInsight | null;
}

export async function getPensionDimension(
  slug: string, key: string, withAi: boolean, audience: string, deep = false,
): Promise<PensionDimensionDetail> {
  const { data } = await client.get(`/pension-intel/${slug}/dimension`, {
    params: { key, with_ai: withAi, audience, ...(deep ? { deep: true } : {}) },
  });
  return data;
}

/** Cartera-position drill-down: weight + nature + its own AI insight. */
export interface PensionCarteraHoldingDetail {
  found: boolean;
  period: string | null;
  fund: string;
  total: number;
  holding: PensionHolding;
  ai_insight: AiInsight | null;
}

export async function getPensionCarteraHolding(
  issuerSlug: string, withAi: boolean, audience: string, deep = false, period?: string,
): Promise<PensionCarteraHoldingDetail> {
  const { data } = await client.get("/pension-intel/cartera/holding", {
    params: { issuer_slug: issuerSlug, with_ai: withAi, audience, ...(period ? { period } : {}), ...(deep ? { deep: true } : {}) },
  });
  return data;
}

// Headline series codes (system level) — stable keys from the backend.
export const HEADLINE_CCI = "sipen.rentabilidad.cci_nominal_anual";
export const HEADLINE_SDP = "sipen.rentabilidad.sdp_nominal_anual";
export const HEADLINE_COMMISSIONS = "sipen.comisiones.total_anual";

/** True when the pulse carries at least one real figure (system or per-AFP). */
export function pulseHasData(p: PensionPulse): boolean {
  return (p.afp_rentabilidad?.ranking?.length ?? 0) > 0 ||
    Object.values(p.headline ?? {}).some((v) => v != null);
}

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

// Headline series codes (system level) — stable keys from the backend.
export const HEADLINE_CCI = "sipen.rentabilidad.cci_nominal_anual";
export const HEADLINE_SDP = "sipen.rentabilidad.sdp_nominal_anual";
export const HEADLINE_COMMISSIONS = "sipen.comisiones.total_anual";

/** True when the pulse carries at least one real figure (system or per-AFP). */
export function pulseHasData(p: PensionPulse): boolean {
  return (p.afp_rentabilidad?.ranking?.length ?? 0) > 0 ||
    Object.values(p.headline ?? {}).some((v) => v != null);
}

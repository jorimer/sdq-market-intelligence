import client from "@/shared/api/client";
import type { AiInsight } from "@/shared/ui/insight-types";

export const INSURANCE_AUDIENCES = ["inversionista", "regulador", "asegurado", "gobierno"] as const;

/** One line of business (ramo) share of the market's premiums. */
export interface RamoMix {
  ramo: string;
  label: string;
  amount: number;
  pct: number | null;
}

/** National SFS health-coverage reading (SISALRIL/CNSS), folded into the pulse. */
export interface HealthCoverage {
  period: string | null;
  afiliados_total: number | null;
  afiliados_contributivo: number | null;
  afiliados_subsidiado: number | null;
  crecimiento_5a_pct: number | null;
  source: string;
}

/** National insurance-market pulse (SIS): size, growth, mix, structure + health coverage. */
export interface InsurancePulse {
  has_data: boolean;
  period: string | null;
  latest_year?: string;
  total_premiums_rd?: number;
  growth_pct?: number | null;
  growth_years?: [string, string] | null;
  mix?: RamoMix[];
  top4_concentration_pct?: number | null;
  active_insurers?: number | null;
  n_ramos?: number;
  data_caveat?: string | null;
  health_coverage?: HealthCoverage | null;
  source: string;
}

export async function getInsurancePulse(): Promise<InsurancePulse> {
  const { data } = await client.get("/insurance-intel/pulse");
  return data;
}

export async function getInsuranceInsight(
  audience: string = INSURANCE_AUDIENCES[0],
  deep = false,
): Promise<AiInsight | null> {
  const { data } = await client.get("/insurance-intel/insight", {
    params: { audience, ...(deep ? { deep: true } : {}) },
  });
  return (data.ai_insight as AiInsight | null) ?? null;
}

/** One insurer row in the ISF ranking (0-100 band index over audited statements). */
export interface InsuranceRankRow {
  rank: number | null;
  slug: string;
  name?: string;
  overall_score: number | null;
  band: string | null;
  coverage: number | null;
  period: string | null;
}

export async function getInsuranceRankings(): Promise<{
  rankings: InsuranceRankRow[];
  count: number;
  scale: string;
  note: string | null;
}> {
  const { data } = await client.get("/insurance-intel/rankings");
  return data;
}

/** One ISF dimension in an insurer's breakdown. */
export interface InsuranceDimension {
  key: string;
  label: string;
  weight: number;
  score: number | null;
  raw: number | null;
  provenance: string;
  present: boolean;
}

export interface InsuranceDetail {
  found: boolean;
  slug: string;
  overall_score: number | null;
  band: string | null;
  coverage: number | null;
  dimensions: InsuranceDimension[];
  note?: string;
}

export async function getInsuranceEntityDetail(slug: string): Promise<InsuranceDetail> {
  const { data } = await client.get(`/insurance-intel/${slug}/detail`);
  return data;
}

export async function getInsuranceEntityInsight(
  slug: string,
  audience: string = INSURANCE_AUDIENCES[0],
  deep = false,
): Promise<AiInsight | null> {
  const { data } = await client.get(`/insurance-intel/entity-insight/${slug}`, {
    params: { audience, ...(deep ? { deep: true } : {}) },
  });
  return (data.ai_insight as AiInsight | null) ?? null;
}

/** True when the pulse carries real market data. */
export function pulseHasData(p: InsurancePulse): boolean {
  return p.has_data && (p.total_premiums_rd ?? 0) > 0;
}

/** One ARS row in the ISARS ranking (health-risk-manager solidity, 0-100). */
export interface ArsRankRow {
  rank: number | null;
  slug: string;
  name: string;
  category: number | string | null; // 1=Autogestionada, 2=Pública, 3=Privada
  overall_score: number | null;
  band: string | null;
  coverage: number | null;
  period: string | null;
}

export async function getArsRankings(): Promise<{
  rankings: ArsRankRow[];
  count: number;
  scale: string;
  note: string | null;
  caveat: string;
}> {
  const { data } = await client.get("/insurance-intel/ars/rankings");
  return data;
}

export const ARS_CATEGORY_LABELS: Record<string, string> = {
  "1": "Autogestionada",
  "2": "Pública",
  "3": "Privada",
};

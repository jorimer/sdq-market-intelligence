import client from "@/shared/api/client";
import type { AiInsight } from "@/shared/ui/insight-types";

export interface IRMPDimension {
  score: number;
  weight: number;
  contribution: number;
  variables: Record<string, { raw: number; normalized: number; inverted: boolean }>;
}

export interface IRMPResult {
  country_code: string;
  irmp_score: number;
  risk_band: string;
  band_color: string;
  dimensions: Record<string, IRMPDimension>;
  peer_set_size: number;
  model_version: string;
  ai_insight?: AiInsight | null;
}

export interface IRMPWeights {
  dimension_weights: Record<string, number>;
  dimension_variables: Record<string, string[]>;
  risk_increasing_variables: string[];
  direction: string;
}

type RegionalDataset = Record<string, Record<string, number>>;

export async function getWeights(): Promise<IRMPWeights> {
  const { data } = await client.get("/macro-political-risk/weights");
  return data;
}

export interface IrmpDataset {
  period: string | null;
  dataset: Record<string, Record<string, number>>;
  sources: Record<string, Record<string, "live" | "rubric">>;
  has_live: boolean;
}

// Full assembled dataset (declared rubric overlaid with live data) + provenance.
// Single source of truth so the UI scores exactly what the snapshot persists.
export async function getDataset(period?: string): Promise<IrmpDataset> {
  const { data } = await client.get("/macro-political-risk/dataset", {
    params: period ? { period } : undefined,
  });
  return data;
}

export async function scoreCountry(
  countryCode: string,
  dataset: RegionalDataset,
  opts?: { withAi?: boolean; countryName?: string },
): Promise<IRMPResult> {
  const { data } = await client.post(
    "/macro-political-risk/score",
    { country_code: countryCode, dataset, country_name: opts?.countryName },
    { params: opts?.withAi ? { with_ai: true } : undefined },
  );
  return data;
}

export async function saveSnapshot(
  countryCode: string,
  dataset: RegionalDataset,
  periodEnd: string,
  countryName?: string,
): Promise<IRMPResult & { snapshot_id: string }> {
  const { data } = await client.post("/macro-political-risk/snapshot", {
    country_code: countryCode,
    dataset,
    period_end: periodEnd,
    country_name: countryName,
  });
  return data;
}

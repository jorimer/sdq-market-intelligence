import client from "@/shared/api/client";

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
}

export interface IRMPWeights {
  dimension_weights: Record<string, number>;
  dimension_variables: Record<string, string[]>;
  risk_increasing_variables: string[];
  direction: string;
}

type RegionalDataset = Record<string, Record<string, number>>;

export interface WgiLive {
  source: string;
  period: string | null;
  has_data: boolean;
  countries: Record<string, Record<string, number>>;
  variables: string[];
}

export async function getWeights(): Promise<IRMPWeights> {
  const { data } = await client.get("/macro-political-risk/weights");
  return data;
}

export async function getWgiLive(period?: string): Promise<WgiLive> {
  const { data } = await client.get("/macro-political-risk/wgi", {
    params: period ? { period } : undefined,
  });
  return data;
}

// All persisted IRMP variables (WGI + WDI + IMF + declared), any source.
export async function getLiveVariables(period?: string): Promise<WgiLive> {
  const { data } = await client.get("/macro-political-risk/variables", {
    params: period ? { period } : undefined,
  });
  return data;
}

export async function scoreCountry(
  countryCode: string,
  dataset: RegionalDataset,
): Promise<IRMPResult> {
  const { data } = await client.post("/macro-political-risk/score", {
    country_code: countryCode,
    dataset,
  });
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

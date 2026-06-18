import client from "@/shared/api/client";
import type { AiInsight } from "@/shared/ui/insight-types";

/** Contextual AI insight for one region's IDM (development narrative). Best-effort. */
export async function getRegionInsight(entityKey: string): Promise<AiInsight | null> {
  const { data } = await client.get(`/social-dev/${entityKey}/insight`);
  return (data.ai_insight as AiInsight | null) ?? null;
}

export interface SocialEntity {
  entity_key: string;
  development_score: number;
  band: string;
}

export interface Distribution {
  n: number;
  mean: number | null;
  min: number | null;
  max: number | null;
  spread: number | null;
  cv: number | null;
}

export interface IndexResult {
  period: string;
  entities: SocialEntity[];
  distribution: Distribution;
}

export interface SdgDetail {
  has_score: boolean;
  entity_key: string;
  period: string;
  development_score: number;
  band: string;
  dimensions: Record<string, { score: number; weight: number; contribution: number }>;
}

export type DimBreakdown = Record<string, { score: number; weight: number; contribution: number }>;

export interface SocialIndicatorRow {
  entity_key: string;
  period: string;
  development_score: number;
  band: string;
  breakdown: DimBreakdown;
}

export interface IndicatorsResult {
  indicators: SocialIndicatorRow[];
  count: number;
  distribution: Distribution;
  period: string | null;
}

export interface IdmDataset {
  period: string | null;
  dataset: Record<string, Record<string, number>>;
  sources: Record<string, Record<string, "live" | "rubric">>;
  has_live: boolean;
}

export async function getWeights() {
  const { data } = await client.get("/social-dev/weights");
  return data as { dimension_weights: Record<string, number>; direction: string };
}

export async function getIndicators(): Promise<IndicatorsResult> {
  const { data } = await client.get("/social-dev/indicators");
  return data;
}

export async function getDataset(): Promise<IdmDataset> {
  const { data } = await client.get("/social-dev/dataset");
  return data;
}

export interface OnePublication {
  id: string;
  report_name: string;
  period: string;
  landing_url: string;
  status: string;
  sectors: string[];
  resumen: string;
  hallazgos: string[];
}

export async function getPublications(): Promise<{ publications: OnePublication[]; count: number }> {
  const { data } = await client.get("/social-dev/publications");
  return data;
}

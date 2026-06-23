import client from "@/shared/api/client";
import type { AiInsight } from "@/shared/ui/insight-types";

export const CLIMATE_AUDIENCES = [
  "inversionista",
  "gobierno",
  "asegurador",
  "multilateral",
] as const;

/** Contextual AI insight for one country's IRC (climate narrative), by audience. */
export async function getCountryInsight(
  entityKey: string,
  audience: string = CLIMATE_AUDIENCES[0],
  deep = false,
): Promise<AiInsight | null> {
  const { data } = await client.get(`/esg-climate/${entityKey}/insight`, {
    params: { audience, ...(deep ? { deep: true } : {}) },
  });
  return (data.ai_insight as AiInsight | null) ?? null;
}

/** One country's IRC (climate resilience) score in the panel. */
export interface IRCIndicator {
  entity_key: string;
  country_name: string;
  period: string;
  esg_score: number;
  band: string;
}

/** Per-country detail with the dimension breakdown + real-vs-rubric sources. */
export interface IRCCountryDetail {
  has_score: boolean;
  entity_key: string;
  country_name?: string;
  period?: string;
  esg_score?: number;
  band?: string;
  breakdown?: {
    dimensions: Record<string, { score: number; weight: number; contribution: number }>;
    sources: Record<string, "live" | "rubric">;
  };
}

export async function getIndicators(): Promise<{ indicators: IRCIndicator[]; count: number; period: string | null }> {
  const { data } = await client.get("/esg-climate/indicators");
  return data;
}

export async function getCountryScore(entityKey: string): Promise<IRCCountryDetail> {
  const { data } = await client.get("/esg-climate/score", { params: { entity_key: entityKey } });
  return data;
}

/** IRC backtest report (validation vs realized climate-disaster mortality). */
export interface IRCBacktest {
  computed: boolean;
  message?: string;
  n_countries?: number;
  outcome?: string;
  spearman?: number | null;
  spearman_ci?: [number | null, number | null];
  by_band?: { band: string; n: number; mean_climate_deaths_per_100k: number | null }[];
  monotonic?: boolean;
  note?: string;
  generated_at?: string;
}

export async function getBacktest(): Promise<IRCBacktest> {
  const { data } = await client.get("/esg-climate/backtest");
  return data;
}

import client from "@/shared/api/client";

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

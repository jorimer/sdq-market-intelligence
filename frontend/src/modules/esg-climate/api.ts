import client from "@/shared/api/client";

export interface Materiality {
  material: boolean;
  level: string;
  greenwashing_watch: boolean;
}

/** A persisted ESG/climate sector score (from /indicators). */
export interface ESGIndicator {
  sector_key: string;
  period: string;
  esg_score: number;
  band: string;
  material: boolean;
  materiality_level: string;
}

/** Per-sector detail with the dimension breakdown (from /score). */
export interface ESGSectorDetail {
  has_score: boolean;
  sector_key: string;
  period?: string;
  esg_score?: number;
  band?: string;
  materiality_level?: string;
  breakdown?: {
    dimensions: Record<string, { score: number; weight: number; contribution: number }>;
    materiality: Materiality;
  };
}

export async function getIndicators(): Promise<{ indicators: ESGIndicator[]; count: number }> {
  const { data } = await client.get("/esg-climate/indicators");
  return data;
}

export async function getSectorScore(sectorKey: string): Promise<ESGSectorDetail> {
  const { data } = await client.get("/esg-climate/score", { params: { sector_key: sectorKey } });
  return data;
}

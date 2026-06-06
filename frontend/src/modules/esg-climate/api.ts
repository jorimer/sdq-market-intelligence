import client from "@/shared/api/client";

export interface Materiality {
  material: boolean;
  level: string;
  greenwashing_watch: boolean;
}

export interface ESGSectorSummary {
  sector_key: string;
  esg_score: number;
  band: string;
  materiality: string;
}

export interface ESGExposure {
  sector_key: string;
  esg_score: number;
  band: string;
  dimensions: Record<string, { score: number; weight: number; contribution: number }>;
  materiality: Materiality;
}

type Dataset = Record<string, Record<string, number>>;

export async function getWeights() {
  const { data } = await client.get("/esg-climate/weights");
  return data as { dimension_weights: Record<string, number>; direction: string };
}

export async function scoreSectors(
  period: string,
  dataset: Dataset,
): Promise<{ period: string; sectors: ESGSectorSummary[] }> {
  const { data } = await client.post("/esg-climate/score", { period, dataset });
  return data;
}

export async function getExposure(sectorKey: string, dataset: Dataset): Promise<ESGExposure> {
  const { data } = await client.post("/esg-climate/exposure", { sector_key: sectorKey, dataset });
  return data;
}

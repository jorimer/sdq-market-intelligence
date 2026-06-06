import client from "@/shared/api/client";

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

type Dataset = Record<string, Record<string, number>>;

export async function getWeights() {
  const { data } = await client.get("/social-dev/weights");
  return data as { dimension_weights: Record<string, number>; direction: string };
}

export async function computeIndex(period: string, dataset: Dataset): Promise<IndexResult> {
  const { data } = await client.post("/social-dev/index", { period, dataset });
  return data;
}

export async function getDetail(entityKey: string): Promise<SdgDetail> {
  const { data } = await client.get("/social-dev/sdg", { params: { entity_key: entityKey } });
  return data;
}

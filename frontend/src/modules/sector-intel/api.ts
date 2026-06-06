import client from "@/shared/api/client";

export interface SectorSummary {
  sector_code: string;
  iai_score: number;
  iai_band: string;
  sgps_score: number;
}

export interface AccelerationDetail {
  acceleration: number;
  base: number;
  components: Record<string, number>;
  inputs_present: string[];
}

export interface SnapshotResult {
  period: string;
  country_code: string;
  acceleration: AccelerationDetail;
  sectors: SectorSummary[];
  model_version: string;
}

export interface SectorLatest {
  has_score: boolean;
  sector_code: string;
  period: string;
  iai_score: number;
  iai_band: string;
  sgps_score: number;
  iai_breakdown: Record<
    string,
    { score: number; weight: number; contribution: number }
  >;
  sgps_breakdown: {
    sgps_score: number;
    factors: Record<string, { value: number; weight: number; contribution: number; imputed: boolean }>;
    acceleration_detail?: AccelerationDetail;
  };
}

type Dataset = Record<string, Record<string, number>>;
type SgpsInputs = Record<string, Record<string, number>>;

export async function getWeights() {
  const { data } = await client.get("/sector-intel/weights");
  return data as {
    iai_dimension_weights: Record<string, number>;
    sgps_weights: Record<string, number>;
    direction: string;
  };
}

export async function snapshot(
  period: string,
  dataset: Dataset,
  sgpsInputs: SgpsInputs,
): Promise<SnapshotResult> {
  const { data } = await client.post("/sector-intel/snapshot", {
    period,
    dataset,
    sgps_inputs: sgpsInputs,
  });
  return data;
}

export async function getLatest(sectorCode: string): Promise<SectorLatest> {
  const { data } = await client.get(`/sector-intel/${sectorCode}/latest`);
  return data;
}

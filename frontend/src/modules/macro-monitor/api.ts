import client from "@/shared/api/client";

export interface MacroIndicator {
  series_code: string;
  latest_period: string | null;
  latest_value: number | null;
  change: number | null;
  pct_change: number | null;
  acceleration: number | null;
  trend: "acelerando" | "desacelerando" | "estable" | "insuficiente";
  volatility: number | null;
  continuity_prob: number | null;
}

export interface MacroSignal {
  signal: string;
  framework: string;
  severity: string;
  series?: string;
  value?: number;
  pct_change?: number;
}

export async function getIndicators(): Promise<MacroIndicator[]> {
  const { data } = await client.get("/macro-monitor/indicators");
  return data.indicators ?? [];
}

export async function getSignals(): Promise<MacroSignal[]> {
  const { data } = await client.get("/macro-monitor/signals");
  return data.signals ?? [];
}

export async function refresh(): Promise<void> {
  await client.post("/macro-monitor/refresh");
}

export interface SeriesDetail {
  series_code: string;
  observations: { period: string; value: number | null }[];
  momentum: {
    latest_value: number | null;
    change: number | null;
    uncertainty_band: [number, number] | null;
  } | null;
}

export async function getSeries(code: string): Promise<SeriesDetail> {
  const { data } = await client.get(`/macro-monitor/series/${code}`);
  return data;
}

import client from "@/shared/api/client";

export interface BankRef {
  id: string;
  name: string;
  bank_type: string | null;
}

export interface SubComponents {
  solidez: number;
  calidad: number;
  eficiencia: number;
  liquidez: number;
  diversificacion: number;
}

export const SUB_KEYS: (keyof SubComponents)[] = [
  "solidez",
  "calidad",
  "eficiencia",
  "liquidez",
  "diversificacion",
];

export const SUB_LABELS: Record<keyof SubComponents, string> = {
  solidez: "Solidez",
  calidad: "Calidad de activos",
  eficiencia: "Eficiencia",
  liquidez: "Liquidez",
  diversificacion: "Diversificación",
};

export interface ScoringResult {
  bank_id?: string;
  bank_name?: string;
  period_end?: string;
  overall_score: number;
  rating_tier: string;
  tier_color?: string;
  sub_components: SubComponents;
  indicators?: Record<string, { raw: number; score: number }>;
  entity_type?: string | null;
}

export async function listBanks(entityType?: string): Promise<BankRef[]> {
  const { data } = await client.get<{ banks: BankRef[] }>("/banking-score/banks", {
    params: entityType ? { entity_type: entityType } : {},
  });
  return data.banks ?? [];
}

export async function listPeriods(): Promise<string[]> {
  const { data } = await client.get<{ periods: string[] }>("/banking-score/periods");
  return data.periods ?? [];
}

export async function runScoring(bankId: string, periodEnd: string): Promise<ScoringResult> {
  const { data } = await client.post<ScoringResult>(
    `/banking-score/${bankId}/run`,
    null,
    { params: { period_end: periodEnd } },
  );
  return data;
}

export async function simulate(
  subComponents: SubComponents,
  entityType?: string,
): Promise<ScoringResult> {
  const { data } = await client.post<ScoringResult>("/banking-score/simulate-scenario", {
    sub_components: subComponents,
    ...(entityType ? { entity_type: entityType } : {}),
  });
  return data;
}

export async function getLatest(bankId: string): Promise<ScoringResult & { has_rating: boolean }> {
  const { data } = await client.get(`/banking-score/${bankId}/latest`);
  return data;
}

/* ── Indicator drill-down (detail + trend + peers + AI insight) ── */

export interface IndicatorPeerStats {
  n: number;
  median_score: number;
  p25_score: number;
  p75_score: number;
  percentile: number;
}

export interface IndicatorDetail {
  bank_id: string;
  bank_name: string;
  indicator: string;
  label: string;
  sub_component: string;
  unit: string;
  direction: string;
  what_it_measures: string;
  latest: {
    period_end: string;
    raw: number | null;
    score: number;
    available: boolean;
    band: string | null;
  };
  interpretation: string;
  trend: { period_end: string; raw: number | null; score: number }[];
  peers: {
    period_end: string;
    sector: IndicatorPeerStats | null;
    entity_type: IndicatorPeerStats | null;
    entity_type_label: string | null;
  } | null;
  ai_insight: { text: string; model_used: string; from_cache: boolean } | null;
}

export async function getIndicatorDetail(
  bankId: string,
  indicatorKey: string,
  withAi = true,
): Promise<IndicatorDetail> {
  // The AI insight takes ~10-15s (Claude detailed); fetch the data with_ai=false
  // for an instant render, then re-fetch with_ai=true to fill the insight in.
  const { data } = await client.get<IndicatorDetail>(
    `/banking-score/${bankId}/indicator/${indicatorKey}`,
    { params: { with_ai: withAi } },
  );
  return data;
}

export interface BankStats {
  total_records: number;
  total_entities: number;
  total_ratings: number;
  period_start: string | null;
  period_end: string | null;
}

export async function getStats(): Promise<BankStats> {
  const { data } = await client.get<BankStats>("/banking-score/stats");
  return data;
}

export interface ReportItem {
  id: string;
  report_type: string | null;
  period_end: string | null;
  status: string | null;
  created_at: string | null;
  file_path: string | null;
}

export async function listReports(bankId: string): Promise<ReportItem[]> {
  const { data } = await client.get<{ reports: ReportItem[] }>(`/banking-score/reports/${bankId}/list`);
  return data.reports ?? [];
}

export async function generateReport(
  bankId: string,
  periodEnd: string,
  reportType: string,
): Promise<void> {
  await client.post(`/banking-score/reports/${bankId}/generate`, null, {
    params: { period_end: periodEnd, report_type: reportType },
  });
}

export async function downloadReport(reportId: string): Promise<void> {
  const r = await client.get(`/banking-score/reports/download/${reportId}`, {
    responseType: "blob",
  });
  const url = URL.createObjectURL(r.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = `reporte_${reportId}.pdf`;
  a.click();
  URL.revokeObjectURL(url);
}

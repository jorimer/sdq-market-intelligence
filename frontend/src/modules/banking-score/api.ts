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

/* ── Entity drill-down (overall + sub-component drivers + peers + AI) ── */

export interface EntitySubComponent {
  key: string;
  label: string;
  score: number | null;
  weight: number | null;
  band: string | null;
  driver: { key: string; label: string; score: number } | null;
  drag: { key: string; label: string; score: number } | null;
}

export interface EntityInsight {
  bank_id: string;
  bank_name: string;
  entity_type: string | null;
  latest: { period_end: string; overall_score: number; rating_tier: string; band: string };
  sub_components: EntitySubComponent[];
  trend: { period_end: string; score: number; tier: string }[];
  peers: {
    period_end: string;
    sector: IndicatorPeerStats | null;
    entity_type: IndicatorPeerStats | null;
    entity_type_label: string | null;
  } | null;
  ai_insight: { text: string; model_used: string; from_cache: boolean } | null;
}

export async function getEntityInsight(bankId: string, withAi = true): Promise<EntityInsight> {
  const { data } = await client.get<EntityInsight>(`/banking-score/${bankId}/insight`, {
    params: { with_ai: withAi },
  });
  return data;
}

/* ── Contextual AI insight cards (comparative · sector · scenario) ── */

export interface AiInsight {
  text: string;
  model_used: string;
  from_cache: boolean;
}

export async function getCompareInsight(bankIds: string[], periodEnd?: string): Promise<AiInsight | null> {
  const { data } = await client.post<{ ai_insight: AiInsight | null }>(
    "/banking-score/insight/compare",
    { bank_ids: bankIds, period_end: periodEnd },
  );
  return data.ai_insight;
}

export async function getSectorInsight(entityType?: string, periodEnd?: string): Promise<AiInsight | null> {
  const { data } = await client.get<{ ai_insight: AiInsight | null }>(
    "/banking-score/insight/sector",
    { params: { entity_type: entityType || undefined, period_end: periodEnd || undefined } },
  );
  return data.ai_insight;
}

export async function getScenarioInsight(
  subComponents: SubComponents,
  entityType?: string,
  base?: { sub_components: SubComponents; overall_score: number },
): Promise<AiInsight | null> {
  const { data } = await client.post<{ ai_insight: AiInsight | null }>(
    "/banking-score/insight/scenario",
    { sub_components: subComponents, entity_type: entityType, base },
  );
  return data.ai_insight;
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

// ─── Fideicomisos públicos (public trusts) — own health index ──────

export interface TrustHealth {
  solvencia: number | null;
  liquidez: number | null;
  sostenibilidad: number | null;
  overall: number | null;
  band: string;
}

export interface TrustFinancials {
  activos_totales: number | null;
  patrimonio_fideicomitido: number | null;
  pasivos_totales: number | null;
  resultado_periodo: number | null;
  ingresos_operacionales: number | null;
}

export interface TrustRow {
  id: string;
  name: string;
  segment: string | null;
  fiduciaria: string | null;
  period_end: string | null;
  health: TrustHealth;
  financials: TrustFinancials | null;
}

export async function getTrusts(): Promise<TrustRow[]> {
  const { data } = await client.get<{ trusts: TrustRow[] }>("/banking-score/trusts");
  return data.trusts ?? [];
}

// ─── Market concentration (system-level: CR10 of the EIF) ──────────

export interface ConcentrationEntity {
  name: string;
  value: number;
  share: number;
}
export interface MarketConcentration {
  period_end: string | null;
  metric: string;
  metric_label?: string;
  available: boolean;
  n_entities?: number;
  total?: number;
  cr5?: number;
  cr10?: number;
  hhi?: number;
  top10?: ConcentrationEntity[];
}

export async function getMarketConcentration(
  metric = "activos",
  periodEnd?: string,
): Promise<MarketConcentration> {
  const { data } = await client.get<MarketConcentration>("/banking-score/market-concentration", {
    params: { metric, ...(periodEnd ? { period_end: periodEnd } : {}) },
  });
  return data;
}

import client from "@/shared/api/client";
import { type Audience, DEFAULT_AUDIENCE } from "./audience";

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
  /** Perfil SDQ: los dos ejes reemplazan al símbolo único (§9). */
  ejecucion: number | null;
  banda_ejecucion: string | null;
  resiliencia: number | null;
  banda_resiliencia: string | null;
  tier_color?: string;
  sub_components: SubComponents;
  indicators?: Record<string, { raw: number; score: number }>;
  entity_type?: string | null;
  model?: "deterministic" | "ml";
  model_version?: string;
  tier_probabilities?: Record<string, number>;
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

export async function runScoring(
  bankId: string,
  periodEnd: string,
  model: "deterministic" | "ml" = "deterministic",
): Promise<ScoringResult> {
  const { data } = await client.post<ScoringResult>(
    `/banking-score/${bankId}/run`,
    null,
    { params: { period_end: periodEnd, model } },
  );
  return data;
}

export async function getModelStatus(): Promise<import("@/types").ModelStatus> {
  const { data } = await client.get<import("@/types").ModelStatus>(
    "/banking-score/model/status",
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

/** Period-ends (ISO, desc) the entity has data for — to tell "sin dato para este
 * período" apart from an error and guide the user to its latest available period. */
export async function getBankPeriods(bankId: string): Promise<string[]> {
  const { data } = await client.get<{ periods: string[] }>(`/banking-score/${bankId}/periods`);
  return data.periods ?? [];
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
  audience: Audience = DEFAULT_AUDIENCE,
  deep = false,
): Promise<IndicatorDetail> {
  // The AI insight takes ~10-15s (Claude detailed); fetch the data with_ai=false
  // for an instant render, then re-fetch with_ai=true to fill the insight in.
  // `audience` orients only the AI insight (same facts, different "y por tanto");
  // `deep` requests the extended "full analysis" version.
  const { data } = await client.get<IndicatorDetail>(
    `/banking-score/${bankId}/indicator/${indicatorKey}`,
    { params: { with_ai: withAi, audience, ...(deep ? { deep: true } : {}) } },
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
  latest: { period_end: string; overall_score: number; band: string;
            ejecucion: number | null; banda_ejecucion: string | null;
            resiliencia: number | null; banda_resiliencia: string | null };
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

export async function getEntityInsight(
  bankId: string,
  withAi = true,
  audience: Audience = DEFAULT_AUDIENCE,
  deep = false,
): Promise<EntityInsight> {
  const { data } = await client.get<EntityInsight>(`/banking-score/${bankId}/insight`, {
    params: { with_ai: withAi, audience, ...(deep ? { deep: true } : {}) },
  });
  return data;
}

/* ── Contextual AI insight cards (comparative · sector · scenario) ── */

// AiInsight now lives in shared/ui (promoted in T1). Re-exported here so existing
// consumers importing it from this module keep working unchanged.
export type { AiInsight } from "@/shared/ui/insight-types";
import type { AiInsight } from "@/shared/ui/insight-types";

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

// ─── Informes de SISTEMA (no cuelgan de una entidad) ───────────────
//
// criteria/wire/datawatch/sector_outlook describen la metodología o el sistema entero, así
// que no aparecen en el listado por banco (su `bank_id` es NULL) ni pueden generarse desde
// el selector de entidad: tienen sus propios endpoints y su propio listado.

export const SYSTEM_REPORT_TYPES = [
  "criteria",
  "wire",
  "datawatch",
  "sector_outlook",
] as const;

export type SystemReportType = (typeof SYSTEM_REPORT_TYPES)[number];

/** `criteria` es la metodología: no depende de un período. */
export const SYSTEM_REPORT_NEEDS_PERIOD: Record<SystemReportType, boolean> = {
  criteria: false,
  wire: true,
  datawatch: true,
  sector_outlook: true,
};

const SYSTEM_REPORT_PATH: Record<SystemReportType, string> = {
  criteria: "criteria",
  wire: "wire",
  datawatch: "datawatch",
  sector_outlook: "sector-outlook",
};

export async function listSystemReports(): Promise<ReportItem[]> {
  const { data } = await client.get<{ reports: ReportItem[] }>(
    "/banking-score/reports/system/list",
  );
  return data.reports ?? [];
}

export async function generateSystemReport(
  reportType: SystemReportType,
  periodEnd: string,
): Promise<void> {
  const params = SYSTEM_REPORT_NEEDS_PERIOD[reportType]
    ? { period_end: periodEnd }
    : undefined;
  await client.post(
    `/banking-score/reports/${SYSTEM_REPORT_PATH[reportType]}/generate`,
    null,
    { params },
  );
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

// ─── Operation Console ──────────────────────────────────────────
// Platform-wide: lives in shared/ops/api. Re-exported here for back-compat.
export {
  getOperationsStatus,
  triggerOperation,
  setOperationSchedule,
} from "@/shared/ops/api";
export type {
  OperationStatus,
  OperationSchedule,
  OperationInfo,
  OperationRunHistory,
  OperationsStatus,
} from "@/shared/ops/api";

// ─── Validación / Backtest (T4) ─────────────────────────────────

export interface BacktestTierRow {
  tier: string;
  n: number;
  events: number;
  rate: number | null;
}

export interface BacktestReport {
  computed: boolean;
  message?: string;
  ok?: boolean;
  horizon_quarters?: number;
  n_observations?: number;
  n_events?: number;
  event_rate?: number;
  gini?: number | null;
  gini_ci?: [number, number] | null;
  by_tier?: BacktestTierRow[];
  monotonic?: boolean;
  caveats?: string[];
  generated_at?: string;
}

export async function getBacktestReport(): Promise<BacktestReport> {
  const { data } = await client.get<BacktestReport>("/banking-score/validation/backtest");
  return data;
}

export async function runBacktest(): Promise<{ started: boolean; reason?: string }> {
  const { data } = await client.post("/banking-score/validation/backtest/run");
  return data;
}

// ── Alerta temprana (early warning) ──
export interface BankAlert {
  code: string;
  label: string;
  severity: "alta" | "media";
  value: number | null;
  threshold: number;
  basis: string;
  metric: string;
}
export interface BankAlerts {
  bank_id: string;
  name: string;
  max_severity: "alta" | "media";
  alerts: BankAlert[];
}
export interface SystemAlerts {
  period: string | null;
  banks: BankAlerts[];
  summary: Record<string, number>;
  n_alerts: number;
}
export async function getSystemAlerts(): Promise<SystemAlerts> {
  const { data } = await client.get<SystemAlerts>("/banking-score/alerts");
  return data;
}

// ── Histórico (Cronología SB): cohorte de quiebras + forense por entidad ─────────

export interface HistoricalEntity {
  nombre: string;
  tipo_entidad: string | null;
  primer: string | null;
  ultimo: string | null;
  n_periodos: number;
  salio_del_sistema: boolean;
}

export interface CohortResult {
  nombre: string;
  episodio: string;
  found: boolean;
  exit_date?: string | null;
  onset_cluster?: string | null;
  lead_months?: number | null;
}

export interface CohortResponse {
  cohort: CohortResult[];
  n_found: number;
  leads: Record<string, number | null>;
}

export interface ForensicSeriesPoint {
  fecha: string;
  activos_totales: number | null;
  morosidad_pct: number | null;
  cobertura_pct: number | null;
  apalancamiento_pct: number | null;
  depositos: number | null;
  dep_mom_pct: number | null;
  patrimonio: number | null;
  utilidad_neta: number | null;
}

export interface ForensicAlert {
  code: string;
  severity: string;
  value: number | null;
}

export interface ForensicTimelinePoint {
  period: string;
  alerts: ForensicAlert[];
}

export interface ForensicPackage {
  meta: {
    nombre: string;
    tipo_entidad: string | null;
    sector: string | null;
    primer: string;
    ultimo: string;
    n_periodos: number;
    salio_del_sistema: boolean;
  };
  series: ForensicSeriesPoint[];
  backtest: {
    exit_date: string | null;
    onset_cluster: string | null;
    first_high_raw: string | null;
    lead_months: number | null;
    n_high_months: number;
    n_flagged_months: number;
    timeline: ForensicTimelinePoint[];
  };
}

const HIST = "/banking-score/historical";

export async function getHistoricalEntities(onlyExited = false): Promise<HistoricalEntity[]> {
  const { data } = await client.get<{ entities: HistoricalEntity[] }>(`${HIST}/entities`, {
    params: { only_exited: onlyExited },
  });
  return data.entities;
}

export async function getCohortBacktest(): Promise<CohortResponse> {
  const { data } = await client.get<CohortResponse>(`${HIST}/cohort`);
  return data;
}

export async function getForensic(nombre: string): Promise<ForensicPackage> {
  const { data } = await client.get<ForensicPackage>(`${HIST}/forensic`, { params: { nombre } });
  return data;
}

export interface ForensicNarrative {
  nombre: string;
  narrative: string;
  degraded: boolean;
}

export async function getForensicNarrative(nombre: string): Promise<ForensicNarrative> {
  const { data } = await client.get<ForensicNarrative>(`${HIST}/forensic/narrative`, {
    params: { nombre },
  });
  return data;
}

/** URL absoluta del informe forense branded (PDF por defecto, o Word con fmt="docx"). */
export function forensicReportUrl(nombre: string, fmt: "pdf" | "docx" = "pdf"): string {
  return `/api/v1${HIST}/forensic/report?nombre=${encodeURIComponent(nombre)}&fmt=${fmt}`;
}

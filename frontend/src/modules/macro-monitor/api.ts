import client from "@/shared/api/client";
import type { AiInsight } from "@/shared/ui/insight-types";

export interface MacroIndicator {
  series_code: string;
  label: string;
  unit: string | null;
  n_obs: number;
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
  ai_insight?: AiInsight | null;
}

/** Detalle de una serie. `withAi` (lento ~10-15s) genera el insight de Claude. */
export async function getSeries(code: string, withAi = false): Promise<SeriesDetail> {
  const { data } = await client.get(`/macro-monitor/series/${code}`, {
    params: { with_ai: withAi },
  });
  return data;
}

export const MACRO_AUDIENCES = ["comite", "inversionista", "gobierno", "empresa"] as const;

/** Insight de IA de la serie (fase 2 — para AiInsightCard). */
export async function getSeriesInsight(
  code: string,
  audience: string = MACRO_AUDIENCES[0],
  deep = false,
): Promise<AiInsight | null> {
  const { data } = await client.get<SeriesDetail>(`/macro-monitor/series/${code}`, {
    params: { with_ai: true, audience, ...(deep ? { deep: true } : {}) },
  });
  return data.ai_insight ?? null;
}

/** Lectura de coyuntura (IA) del snapshot macro (fase 2 — para AiInsightCard). */
export async function getMacroSnapshotInsight(
  period?: string,
  audience: string = MACRO_AUDIENCES[0],
  deep = false,
): Promise<AiInsight | null> {
  const { data } = await client.get<{ ai_insight: AiInsight | null }>(
    "/macro-monitor/snapshot",
    { params: { with_ai: true, audience, ...(period ? { period } : {}), ...(deep ? { deep: true } : {}) } },
  );
  return data.ai_insight ?? null;
}

/** Admin: borra todas las observaciones de un series_code. Devuelve cuántas se borraron. */
export async function deleteSeries(code: string): Promise<number> {
  const { data } = await client.delete(`/macro-monitor/series/${encodeURIComponent(code)}`);
  return data.deleted ?? 0;
}

/** Admin: backfill del histórico BCRD (IPC + tipo de cambio) vía API. */
export interface BackfillResult {
  touched: number;
  series: Record<string, number>;
  period_min: string | null;
  period_max: string | null;
}
export async function backfillHistorico(yearFrom: number, yearTo: number): Promise<BackfillResult> {
  const { data } = await client.post(
    `/macro-monitor/backfill-historico?year_from=${yearFrom}&year_to=${yearTo}`,
  );
  return data;
}

// ── Histórico Excel (motor de ingesta AI-native) ──────────────────
export interface ExcelFeatured {
  key: string;
  label: string;
  sector: string;
  ext: string;
  url: string;
}
export interface ExcelCatalog {
  total: number;
  by_sector: Record<string, number>;
  by_ext: Record<string, number>;
  featured: ExcelFeatured[];
}
export async function getExcelCatalog(): Promise<ExcelCatalog> {
  const { data } = await client.get("/macro-monitor/excel/catalog");
  return data;
}

export interface ExcelSeriesRow {
  code: string;
  unit: string | null;
  n_obs: number;
  n_missing: number;
  period_min: string | null;
  period_max: string | null;
  ok: boolean;
  flags: string[];
}
export interface ExcelIngestResult {
  file: string;
  method: string;
  confidence: number;
  orientation: string;
  records: number;
  series_count: number;
  validation_ok: boolean;
  series: ExcelSeriesRow[];
  dry_run: boolean;
  touched: number;
}
/** Admin: corre el motor sobre un Excel del BCRD. dry_run=true solo reporta. */
export async function ingestExcel(opts: {
  key?: string;
  url?: string;
  dryRun: boolean;
}): Promise<ExcelIngestResult> {
  const params = new URLSearchParams();
  if (opts.key) params.set("key", opts.key);
  if (opts.url) params.set("url", opts.url);
  params.set("dry_run", String(opts.dryRun));
  const { data } = await client.post(`/macro-monitor/excel/ingest?${params.toString()}`);
  return data;
}

// ── Barrido del corpus + cobertura ────────────────────────────────
export interface ExcelAttention {
  filename: string | null;
  sector: string | null;
  status: "flagged" | "failed";
  orientation: string | null;
  frequency: string | null;
  confidence: number | null;
  n_series: number;
  n_flagged: number;
  error: string | null;
  flags: { code: string; flags: string[] }[];
}
export interface ExcelCoverage {
  total_catalog: number;
  reported: number;
  by_status: Record<string, number>;
  by_method: Record<string, number>;
  by_frequency: Record<string, number>;
  attention: ExcelAttention[];
  status: { is_running: boolean; done: number; total: number; started_at: string | null };
}
export async function getExcelCoverage(): Promise<ExcelCoverage> {
  const { data } = await client.get("/macro-monitor/excel/coverage");
  return data;
}
// ── Registro canónico (selección base-homogénea) ──────────────────
export interface CanonicalExtraction {
  status: "ok" | "flagged" | "failed";
  n_series: number;
  method: string | null;
  orientation: string | null;
}
export interface CanonicalSeries {
  key: string;
  concept: string;
  sector: string;
  source_file: string;
  base: string;
  frequency: string;
  homogenization: string;
  rationale: string;
  robustness: "green" | "yellow" | "red";
  api_series: string | null;
  api_transform: string | null;
  extraction: CanonicalExtraction | null;
}
export async function getCanonical(): Promise<{ series: CanonicalSeries[]; count: number }> {
  const { data } = await client.get("/macro-monitor/excel/canonical");
  return data;
}
/** Admin: lanza en segundo plano la ingesta del set canónico (no los 708). */
export async function ingestCanonical(persist: boolean): Promise<{
  status: string;
  via?: string;
  message: string;
}> {
  const { data } = await client.post(`/macro-monitor/excel/ingest-canonical?persist=${persist}`);
  return data;
}

// ── Cruce contra el API (validación de correctitud) ───────────────
export interface CrosscheckResult {
  label: string;
  api_series?: string;
  transform?: string;
  note?: string;
  n_compared?: number;
  n_match?: number;
  n_mismatch?: number;
  max_abs_err?: number;
  period_min?: string | null;
  period_max?: string | null;
  ok?: boolean;
  api_obs?: number;
  examples?: { period: string; excel: number; api: number; abs_err: number }[];
  error?: string;
}
export async function getCrosscheck(): Promise<{
  results: CrosscheckResult[];
  checks: number;
  ok: number;
}> {
  const { data } = await client.get("/macro-monitor/excel/crosscheck");
  return data;
}

/** Admin: lanza el barrido del motor sobre el catálogo en segundo plano. */
export async function runExcelBatch(opts: {
  sector?: string;
  limit?: number;
  persist?: boolean;
  force?: boolean;
}): Promise<{ status: string; via?: string; message: string }> {
  const params = new URLSearchParams();
  if (opts.sector) params.set("sector", opts.sector);
  if (opts.limit != null) params.set("limit", String(opts.limit));
  if (opts.persist) params.set("persist", "true");
  if (opts.force) params.set("force", "true");
  const { data } = await client.post(`/macro-monitor/excel/batch?${params.toString()}`);
  return data;
}

// ── Pulso fiscal (Eje 2: Hacienda Estado de Operaciones + DGII recaudación) ──
export interface FiscalPoint {
  period: string;
  value: number;
}
export interface FiscalRecaudacionGroup {
  slug: string;
  label: string;
  value: number;
}
export interface FiscalPulse {
  has_data: boolean;
  period_range?: [string, string];
  latest_period?: string | null;
  eo_unit?: string;
  eo?: { ingresos: FiscalPoint[]; gastos: FiscalPoint[]; balance_global: FiscalPoint[] };
  eo_latest?: { ingresos: number | null; gastos: number | null; balance_global: number | null };
  recaudacion_unit?: string;
  recaudacion?: { period: string | null; groups: FiscalRecaudacionGroup[] };
}

export async function getFiscalPulse(): Promise<FiscalPulse> {
  const { data } = await client.get("/macro-monitor/fiscal");
  return data;
}

export async function getFiscalInsight(
  audience: string = MACRO_AUDIENCES[0],
  deep = false,
): Promise<AiInsight | null> {
  const { data } = await client.get<{ ai_insight: AiInsight | null }>(
    "/macro-monitor/fiscal/insight", { params: { audience, ...(deep ? { deep: true } : {}) } });
  return data.ai_insight ?? null;
}

// ── Comunicados de Política Monetaria (decisiones de TPM) ─────────
export type TpmAction = "hold" | "cut" | "hike";

export interface Comunicado {
  id: string;
  article_id: number;
  title: string;
  date: string | null;
  action: TpmAction | null;
  tpm_level: number | null;
  bps_change: number | null;
  source_url: string;
  status: string;
}

export interface ComunicadoDigest {
  resumen?: string;
  hallazgos?: string[];
  cifras?: { etiqueta: string; valor: string }[];
  riesgos?: string[];
}

export interface ComunicadoLatest extends Comunicado {
  has_comunicado: boolean;
  digest: ComunicadoDigest | null;
}

export async function getComunicados(limit = 24): Promise<{ comunicados: Comunicado[]; count: number }> {
  const { data } = await client.get("/macro-monitor/comunicados", { params: { limit } });
  return { comunicados: data.comunicados ?? [], count: data.count ?? 0 };
}

export async function getComunicadoLatest(): Promise<ComunicadoLatest | null> {
  const { data } = await client.get<ComunicadoLatest>("/macro-monitor/comunicados/latest");
  return data.has_comunicado ? data : null;
}

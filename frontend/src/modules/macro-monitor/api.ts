import client from "@/shared/api/client";

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
}

export async function getSeries(code: string): Promise<SeriesDetail> {
  const { data } = await client.get(`/macro-monitor/series/${code}`);
  return data;
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

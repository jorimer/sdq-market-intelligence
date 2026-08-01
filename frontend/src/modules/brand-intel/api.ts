import client from "@/shared/api/client";

/** An engagement is one client's brand-tracker mandate. Private data, isolated per client. */
/** Quien contrata. Un cliente agrupa varios estudios, no solo su tracker. */
export interface BrandClient {
  code: string;
  name: string;
  id: string;
  organization_id: string | null;
  engagements: number;
}

export interface Engagement {
  slug: string;
  client: string;
  /** Código del cliente al que pertenece; null en estudios anteriores a la entidad. */
  client_code?: string | null;
  focal_brand: string;
  market: string;
  category: string | null;
  provider: string | null;
  waves: number;
}

export interface WaveRef {
  code: string;
  label: string;
}

export interface ShareSeries {
  brand: string;
  name: string;
  is_focal: boolean;
  series: { wave: string; share: number | null }[];
}

export interface DivergencePoint {
  wave: string;
  label: string;
  attitude: number | null;
  behaviour: number | null;
}

export interface DivergenceReading {
  wave_from: string;
  wave_to: string;
  delta_attitude: number;
  delta_behaviour: number;
  diverging: boolean;
  direction: "converting_above_attitude" | "attitude_above_conversion" | "aligned";
}

export interface CategoryAnalysis {
  available: boolean;
  reason?: string;
  waves?: WaveRef[];
  category_size?: { wave: string; value: number | null }[];
  category_growth_pct?: number | null;
  share?: ShareSeries[];
  share_shift?: { brand: string; name: string; delta: number }[];
  divergence?: DivergencePoint[];
  divergence_reading?: DivergenceReading | null;
  focal?: string;
  denominator_note?: string;
}

export interface FunnelBrand {
  brand: string;
  name: string;
  is_focal: boolean;
  rungs: { metric: string; label: string; value: number | null }[];
  steps: { label: string; conversion: number | null }[];
  end_to_end: number | null;
}

export interface FunnelAnalysis {
  available: boolean;
  reason?: string;
  wave?: WaveRef;
  funnels?: FunnelBrand[];
  weakest_step?: {
    step_label: string;
    focal_conversion: number;
    leader: string;
    leader_name?: string;
    leader_conversion: number;
    gap: number;
  } | null;
}

export interface TicketAnalysis {
  available: boolean;
  deflated?: boolean;
  reason?: string;
  base_wave?: string | null;
  series?: { wave: string; label: string; nominal: number | null; real: number | null }[];
  peak_wave?: string | null;
  change_from_peak_pct?: number | null;
  deflator_note?: string;
  coverage?: number;
}

export interface SignalRow {
  metric_code: string;
  label: string;
  segment: string;
  value: number;
  base_n: number | null;
  threshold: number | null;
  publishable: boolean;
  note: string;
}

export interface SignalFilter {
  available: boolean;
  reason?: string;
  wave?: WaveRef;
  rows?: SignalRow[];
  note?: string;
}

export type DecisionStatus =
  | "open" | "achieved" | "worsened" | "not_detectable" | "unevaluable";

export interface DecisionRow {
  id: string;
  title: string;
  metric: string;
  label: string;
  segment: string;
  owner: string | null;
  baseline_wave: string | null;
  target_wave: string | null;
  baseline_value: number | null;
  target_value: number | null;
  status: DecisionStatus;
  observed_delta: number | null;
  detectable_threshold: number | null;
  note: string;
}

export interface DecisionsPayload {
  decisions: DecisionRow[];
  summary: {
    total: number; achieved: number; worsened: number;
    inconclusive: number; unevaluable: number; open: number; closed: number;
  };
}

export interface BacktestPayload {
  available: boolean;
  reason?: string;
  ranking?: { rule: string; mae: number; n_series: number }[];
  winner?: string;
  n_series?: number;
  note?: string;
}

export interface TrackRecord {
  available: boolean;
  reason?: string;
  n?: number;
  hit_rate?: number;
  mae?: number;
}

/** S3 — one indicator's movement split between category and brand, placed in its cycle. */
export interface AttributionRow {
  metric_code: string;
  label: string;
  delta: number;
  category_effect: number | null;
  brand_effect: number | null;
  verdict: "marca" | "categoria" | "mixto" | "solo_marca" | "sin_movimiento";
  note: string;
  cycle_reading: string;
  cycle_text: string;
}

export interface Environment {
  available: boolean;
  stance: string;
  index: number | null;
  adverse: number;
  favourable: number;
  neutral: number;
  drivers: { label: string; direction: string; magnitude: string; reading: string }[];
  note: string;
}

export interface AttributionAnalysis {
  available: boolean;
  reason?: string;
  wave_from_label?: string;
  wave_to_label?: string;
  category_delta_pct?: number | null;
  environment?: Environment;
  rows?: AttributionRow[];
  note?: string;
}

/** S4 — how to read the frozen forecast, and what could invalidate it. */
export interface ScenarioRow {
  key: string;
  label: string;
  assumptions: string[];
  band_reading: "simetrica" | "sesgo_a_la_baja" | "sesgo_al_alza";
  probability_note: string;
  text: string;
}

export interface ScenariosAnalysis {
  available: boolean;
  reason?: string;
  environment?: Environment;
  scenarios?: ScenarioRow[];
  rule_dispersion?: {
    metric_code: string; label: string; by_rule: Record<string, number>;
    spread: number; robust: boolean; note: string;
  }[];
  risks?: { risk: string; detail: string }[];
  note?: string;
}

/** S5 — what moved, and the agenda the quarter justifies. */
export interface VigilanceSignal {
  source: "macro" | "tracker" | "forecast" | "decision";
  label: string;
  reading: string;
  direction: string;
  strength: "confirmada" | "marginal" | "contextual";
  detail: string;
}

export interface AgendaItem {
  title: string;
  priority: "alta" | "media" | "baja";
  rationale: string;
  evidence: string[];
  source: string;
}

export interface VigilanceAnalysis {
  available: boolean;
  reason?: string;
  environment?: Environment;
  signals?: Record<string, VigilanceSignal[]>;
  agenda?: {
    items: AgendaItem[];
    dropped: number;
    note: string;
    empty_reason: string | null;
  };
  note?: string;
}

export interface IngestReport {
  olas: { creadas: number; actualizadas: number };
  marcas: { creadas: number; actualizadas: number };
  observaciones: { creadas: number; actualizadas: number };
  rechazadas: { sheet: string; row: number; reason: string }[];
  advertencias: string[];
  total_rechazadas: number;
}

/** A presentation read into staging — proposals, not observations. */
export interface PdfIngestReport {
  extraction_id: string | null;
  paginas: { leidas: number; omitidas: number };
  celdas_extraidas: number;
  rechazadas: { page: number; reason: string; detail: string }[];
  errores_por_pagina: { page: number; error: string }[];
  validacion: {
    total: number; passed: number; failed: number;
    unchecked: number; conflict: number; clean: boolean;
    findings: { kind: string; id: string; detail: string }[];
  };
  nota_cobertura: string;
  total_rechazadas: number;
}

export type CellValidation = "passed" | "failed" | "unchecked" | "conflict";

export interface ExtractionCell {
  id: string;
  page: number | null;
  chart: string | null;
  wave: string | null;
  brand: string | null;
  metric: string;
  label: string;
  segment: string;
  value: number;
  base_n: number | null;
  source_method: string;
  validation: CellValidation;
  validation_note: string;
  included: boolean;
}

export interface ExtractionDetail {
  id: string;
  document: string;
  status: string;
  note: string | null;
  summary: PdfIngestReport["validacion"] | null;
  cells: ExtractionCell[];
}

export interface ExtractionSummary {
  id: string;
  document: string;
  pages: number | null;
  status: string;
  method: string;
  model: string | null;
  summary: PdfIngestReport["validacion"] | null;
  note: string | null;
  confirmed_by: string | null;
  created_at: string | null;
}

export interface Feasibility {
  feasible: boolean;
  detectable_threshold: number | null;
  reason: string;
  baseline_value: number | null;
  baseline_base_n: number | null;
}

const base = "/brand-intel";

export interface EngagementInput {
  /** Código del cliente. Sin él, el estudio queda sin agrupar. */
  client?: string;
  slug: string;
  client_name: string;
  focal_brand: string;
  market?: string;
  category?: string;
  research_provider?: string;
}

export interface EngagementDetail {
  slug: string;
  client: string;
  focal_brand: string;
  market: string;
  category: string | null;
  provider: string | null;
  waves: { code: string; label: string; order: number; period: string | null; base: number | null }[];
  brands: { slug: string; name: string; is_focal: boolean; in_category_set: boolean }[];
}

export interface DecisionInput {
  title: string;
  metric_code: string;
  baseline_wave_code: string;
  rationale?: string;
  segment?: string;
  brand_slug?: string | null;
  target_wave_code?: string;
  success_threshold?: number;
  owner?: string;
}

export interface ForecastIssued {
  issued: { metric: string; label: string; point: number; lo: number; hi: number;
            rule: string; basis: string }[];
  skipped: { metric: string; label: string; reason: string }[];
  target_wave?: string;
  error?: string;
}

export async function listEngagements(): Promise<Engagement[]> {
  const { data } = await client.get(`${base}/engagements`);
  return data;
}

export async function getEngagementDetail(slug: string): Promise<EngagementDetail> {
  const { data } = await client.get(`${base}/engagements/${slug}`);
  return data;
}

export async function listClients(): Promise<BrandClient[]> {
  const { data } = await client.get(`${base}/clients`);
  return data;
}

export async function createClient(payload: {
  code: string; name: string; organization_id?: string | null;
}): Promise<BrandClient> {
  const { data } = await client.post(`${base}/clients`, payload);
  return data;
}

export async function createEngagement(
  payload: EngagementInput,
): Promise<{ slug: string; id: string }> {
  const { data } = await client.post(`${base}/engagements`, payload);
  return data;
}

/**
 * Erases the engagement and everything under it. There is no undo.
 *
 * The slug travels twice on purpose — the backend refuses the request unless `confirm`
 * matches — so a DELETE cannot be replayed from a stale tab or a copied URL.
 */
export async function deleteEngagement(
  slug: string,
): Promise<{ deleted: string; removed: Record<string, number> }> {
  const { data } = await client.delete(`${base}/engagements/${slug}`, {
    params: { confirm: slug },
  });
  return data;
}

export async function createDecision(
  slug: string, payload: DecisionInput,
): Promise<{ id: string; status: DecisionStatus; feasibility: Feasibility }> {
  const { data } = await client.post(`${base}/engagements/${slug}/decisions`, payload);
  return data;
}

export async function issueForecast(slug: string, wave: string): Promise<ForecastIssued> {
  const { data } = await client.post(
    `${base}/engagements/${slug}/forecast/issue`, null, { params: { wave } },
  );
  return data;
}

export async function scoreForecasts(
  slug: string,
): Promise<{ scored: { label: string; actual: number; inside_band: boolean; note: string }[]; n: number }> {
  const { data } = await client.post(`${base}/engagements/${slug}/forecast/score`);
  return data;
}

export async function getCategory(slug: string): Promise<CategoryAnalysis> {
  const { data } = await client.get(`${base}/engagements/${slug}/category`);
  return data;
}

export async function getFunnel(slug: string): Promise<FunnelAnalysis> {
  const { data } = await client.get(`${base}/engagements/${slug}/funnel`);
  return data;
}

export async function getTicket(slug: string): Promise<TicketAnalysis> {
  const { data } = await client.get(`${base}/engagements/${slug}/ticket`);
  return data;
}

export async function getSignalFilter(slug: string): Promise<SignalFilter> {
  const { data } = await client.get(`${base}/engagements/${slug}/signal-filter`);
  return data;
}

export async function getDecisions(slug: string): Promise<DecisionsPayload> {
  const { data } = await client.get(`${base}/engagements/${slug}/decisions`);
  return data;
}

export async function getBacktest(slug: string): Promise<BacktestPayload> {
  const { data } = await client.get(`${base}/engagements/${slug}/forecast/backtest`);
  return data;
}

export async function getAttribution(slug: string): Promise<AttributionAnalysis> {
  const { data } = await client.get(`${base}/engagements/${slug}/attribution`);
  return data;
}

export async function getScenarios(slug: string): Promise<ScenariosAnalysis> {
  const { data } = await client.get(`${base}/engagements/${slug}/scenarios`);
  return data;
}

export async function getVigilance(slug: string): Promise<VigilanceAnalysis> {
  const { data } = await client.get(`${base}/engagements/${slug}/vigilance`);
  return data;
}

export async function getTrackRecord(slug: string): Promise<TrackRecord> {
  const { data } = await client.get(`${base}/engagements/${slug}/forecast/track-record`);
  return data;
}

export async function checkDecision(
  slug: string,
  body: {
    metric_code: string;
    baseline_wave_code: string;
    segment?: string;
    brand_slug?: string | null;
    success_threshold?: number | null;
  },
): Promise<Feasibility> {
  const { data } = await client.post(`${base}/engagements/${slug}/decisions/check`, body);
  return data;
}

/** Un trabajo de lectura en curso, o terminado. */
export interface ExtractionJob {
  extraction_id: string;
  document: string;
  status: "queued" | "reading" | "validated" | "rejected" | "confirmed" | "error";
  running: boolean;
  pages_done: number;
  pages_total: number;
  cells_staged: number;
  error: string | null;
  report: PdfIngestReport | null;
  note: string | null;
}

/**
 * Encola la lectura del mazo. Devuelve de inmediato: no espera a que lea.
 *
 * Leer un mazo real son decenas de llamadas de visión. Esperarlas dentro de la petición
 * moría contra el presupuesto de tiempo del proxy después de haberlas pagado todas, sin
 * dejar nada. El avance se consulta con `getExtractionStatus`.
 */
export async function uploadPdf(
  slug: string, file: File, maxPages?: number,
): Promise<ExtractionJob> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await client.post(`${base}/engagements/${slug}/ingest-pdf`, form, {
    headers: { "Content-Type": "multipart/form-data" },
    params: maxPages ? { max_pages: maxPages } : undefined,
    // Solo sube el fichero y encola; un mazo grande tarda en viajar, nada más.
    timeout: 5 * 60 * 1000,
  });
  return data;
}

export async function getExtractionStatus(
  slug: string, extractionId: string,
): Promise<ExtractionJob> {
  const { data } = await client.get(
    `${base}/engagements/${slug}/extractions/${extractionId}/status`);
  return data;
}

/** Vuelve a despachar un trabajo interrumpido. No repaga las láminas ya leídas. */
export async function resumeExtraction(
  slug: string, extractionId: string,
): Promise<ExtractionJob> {
  const { data } = await client.post(
    `${base}/engagements/${slug}/extractions/${extractionId}/resume`);
  return data;
}

export interface WaveCandidate {
  code: string;
  label: string;
  period_date: string;
  occurrences: number;
  pages: number[];
  spellings: string[];
}

export interface BrandCandidate {
  name: string;
  occurrences: number;
  pages: number[];
  spellings: string[];
}

/** Un indicador que el mazo mide, con el tipo que el lector propuso. */
export interface MetricCandidate {
  code: string;
  label: string;
  kind: "proportion" | "index" | "currency" | "count";
  evidence: string;
  confident: boolean;
  pages: number[];
  /** Solo `proportion` admite banda de confianza. */
  supports_bands: boolean;
}

export interface StructureProposal {
  document: string;
  waves: WaveCandidate[];
  brands: BrandCandidate[];
  n_pages: number;
  pages_sampled: number[];
  brand_pass_error: string;
  discarded_waves: { label: string; occurrences: number; pages: number[] }[];
  metrics: MetricCandidate[];
  metric_pass_error: string;
  note: string;
}

export interface AdoptionResult {
  waves_created: number;
  waves_updated: number;
  brands_created: number;
  brands_updated: number;
  metrics_created: number;
  metrics_updated: number;
  warnings: string[];
}

/** Reads the deck's own vocabulary. Creates nothing — the reviewer adopts. */
export async function discoverStructure(
  slug: string, file: File, sample = 5, withMetrics = false,
): Promise<StructureProposal> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await client.post(`${base}/engagements/${slug}/discover`, form, {
    headers: { "Content-Type": "multipart/form-data" },
    params: { sample, with_metrics: withMetrics },
    // A handful of slides still means a handful of vision calls.
    timeout: 10 * 60 * 1000,
  });
  return data;
}

export async function adoptStructure(
  slug: string,
  payload: {
    waves: { code: string; label: string; period_date?: string | null;
             nominal_base?: number | null }[];
    brands: { name: string; slug?: string; is_focal: boolean;
              in_category_set: boolean }[];
    metrics?: { code: string; label: string; kind: string; is_core?: boolean }[];
  },
): Promise<AdoptionResult> {
  const { data } = await client.post(`${base}/engagements/${slug}/structure`, payload);
  return data;
}

export async function listExtractions(slug: string): Promise<ExtractionSummary[]> {
  const { data } = await client.get(`${base}/engagements/${slug}/extractions`);
  return data;
}

export async function getExtraction(
  slug: string, extractionId: string,
): Promise<ExtractionDetail> {
  const { data } = await client.get(
    `${base}/engagements/${slug}/extractions/${extractionId}`,
  );
  return data;
}

/** One observation key read twice with two different numbers. Neither is promoted. */
export interface CellDisagreement {
  marca: string;
  metrica: string;
  segmento: string;
  laminas: number[];
  valores: number[];
}

/** Una cifra que esta entrega mueve — o que quiso mover y no le tocaba. */
export interface FigureChange {
  marca: string;
  metrica: string;
  ola: string;
  segmento: string;
  /** Cuando este mazo manda: lo que había y lo que queda. */
  anterior?: number;
  corregida?: number;
  /** Cuando manda un mazo más nuevo: lo vigente y lo que traía este. */
  vigente?: number;
  esta_entrega?: number;
  entrega_vigente: string;
  este: string;
}

export interface ConfirmResult {
  creadas: number;
  actualizadas: number;
  omitidas_por_inconsistencia: number;
  descartadas_por_revision: number;
  repetidas_coincidentes: number;
  omitidas_por_discrepancia: number;
  discrepancias: CellDisagreement[];
  /** Cifras que este mazo trae distintas pero NO reemplazan: manda una entrega posterior. */
  no_reemplazan_por_entrega_mas_nueva: number;
  cifras_que_cambian: FigureChange[];
  /** Ola más reciente del mazo: lo que decide la precedencia. */
  anada_de_la_entrega: string;
  confirmada_por: string;
}

export async function confirmExtraction(
  slug: string, extractionId: string,
  decisions: { cell_id: string; included: boolean }[],
): Promise<ConfirmResult> {
  const { data } = await client.post(
    `${base}/engagements/${slug}/extractions/${extractionId}/confirm`, decisions,
  );
  return data;
}

export async function uploadWorkbook(slug: string, file: File): Promise<IngestReport> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await client.post(`${base}/engagements/${slug}/ingest`, form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

/** Template and report are streamed as files: fetch as blobs so auth headers apply. */
export async function downloadTemplate(slug: string): Promise<void> {
  const { data } = await client.get(`${base}/template.xlsx`, {
    params: { engagement: slug },
    responseType: "blob",
  });
  triggerDownload(data, `SDQ-MIP_plantilla_tracker_${slug}.xlsx`);
}

/**
 * The report as a file, the same way every other document in the platform is delivered.
 *
 * It used to open a blob URL in a new tab. A blob `window.open` is what popup blockers
 * and embedded browsers drop first, and when they do the click produces nothing at all —
 * no tab, no file, no error — for the one artefact the engagement exists to produce.
 * Downloading cannot be swallowed, and the file is a self-contained page the client can
 * open, read and print to PDF.
 */
export async function downloadReport(slug: string): Promise<void> {
  const { data } = await client.get(`${base}/engagements/${slug}/report.html`, {
    responseType: "blob",
  });
  triggerDownload(new Blob([data], { type: "text/html" }),
                  `SDQ-MIP_informe_contexto_${slug}.html`);
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

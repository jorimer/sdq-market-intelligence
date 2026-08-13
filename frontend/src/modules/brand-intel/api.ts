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


/** Lo que el tablero de ventas dejó entrar — y lo que descartó, que es igual de útil. */
export interface SalesIngestReport {
  filas_leidas: number;
  filas_guardadas: number;
  filas_descartadas: number;
  motivos_descarte: Record<string, number>;
  locales: number;
  plazas: string[];
  desde: string | null;
  hasta: string | null;
  /** Rótulos que PARECÍAN un dato y quedaron fuera: la única alarma real. */
  columnas_sin_mapear: string[];
  /** Rótulos que se ignoran a propósito, con el motivo (derivadas, proyecciones…). */
  columnas_ignoradas: Record<string, string>;
}

export interface SeriesUploadResult {
  lectura: SalesIngestReport | Record<string, unknown>;
  guardado: Record<string, unknown>;
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
  /** El atributo que la cifra califica; null en las métricas que no se miden por atributo. */
  attribute: string | null;
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
  /** La medida es UNA: métrica del tracker XOR fuente externa declarada. */
  metric_code?: string | null;
  external_measure?: string | null;
  baseline_wave_code: string;
  rationale?: string;
  segment?: string;
  brand_slug?: string | null;
  target_wave_code?: string;
  success_threshold?: number;
  owner?: string;
}

// ── planes del cliente ──────────────────────────────────────────────

export type PlanGoalStatus = "propuesta" | "adoptada" | "descartada";

export interface PlanGoal {
  id: string;
  claim: string;
  page_number: number | null;
  kind: "meta" | "accion";
  metric_code: string | null;
  segment: string;
  target_from: number | null;
  target_to: number | null;
  expected_move: number | null;
  owner_declared: string | null;
  measure_source: string | null;
  confident: boolean;
  status: PlanGoalStatus;
  adopted_decision_id: string | null;
  dismiss_note: string | null;
}

export interface PlanDocument {
  id: string;
  filename: string;
  title: string | null;
  source_org: string | null;
  uploaded_by: string | null;
  page_count: number | null;
  status: "propuesto" | "revisado";
  note: string | null;
  created_at: string | null;
  goals: { total: number; propuestas: number; adoptadas: number; descartadas: number };
}

export interface PlanDetail extends PlanDocument {
  metas: PlanGoal[];
}

export interface AdoptGoalInput {
  title?: string;
  metric_code?: string | null;
  external_measure?: string | null;
  segment?: string;
  brand_slug?: string | null;
  baseline_wave_code: string;
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
    metric_code?: string | null;
    external_measure?: string | null;
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
  status: "queued" | "reading" | "validated" | "rejected" | "confirmed" | "error"
        | "cancelled";
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

/**
 * Sube un plan del cliente (.pdf o .html) y deja sus metas como PROPUESTAS.
 *
 * Síncrono: el lector trabaja sobre la capa de texto (1-2 llamadas), no la pasada de
 * visión por lámina de los mazos. Nada entra al ledger aquí — el portón es la adopción.
 */
export async function uploadPlan(
  slug: string, file: File,
): Promise<PlanDocument & { lectura: Record<string, number> }> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await client.post(`${base}/engagements/${slug}/plans`, form, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 5 * 60 * 1000,
  });
  return data;
}

export async function listPlans(slug: string): Promise<PlanDocument[]> {
  const { data } = await client.get(`${base}/engagements/${slug}/plans`);
  return data;
}

export async function getPlanDetail(slug: string, planId: string): Promise<PlanDetail> {
  const { data } = await client.get(`${base}/engagements/${slug}/plans/${planId}`);
  return data;
}

export async function adoptPlanGoal(
  slug: string, planId: string, goalId: string, payload: AdoptGoalInput,
): Promise<{ decision_id: string; status: DecisionStatus; feasibility: Feasibility;
             goal: PlanGoal }> {
  const { data } = await client.post(
    `${base}/engagements/${slug}/plans/${planId}/goals/${goalId}/adopt`, payload);
  return data;
}

export async function dismissPlanGoal(
  slug: string, planId: string, goalId: string, note: string,
): Promise<PlanGoal> {
  const { data } = await client.post(
    `${base}/engagements/${slug}/plans/${planId}/goals/${goalId}/dismiss`, { note });
  return data;
}

export async function getExtractionStatus(
  slug: string, extractionId: string,
): Promise<ExtractionJob> {
  const { data } = await client.get(
    `${base}/engagements/${slug}/extractions/${extractionId}/status`);
  return data;
}

/**
 * Vuelve a despachar un trabajo interrumpido, RETOMANDO en la lámina siguiente a la última
 * leída. Las anteriores no se vuelven a pagar y sus celdas no se duplican.
 */
export async function resumeExtraction(
  slug: string, extractionId: string,
): Promise<ExtractionJob> {
  const { data } = await client.post(
    `${base}/engagements/${slug}/extractions/${extractionId}/resume`);
  return data;
}

export interface CancelResult {
  extraction_id: string;
  status: "cancelled";
  nota: string;
  laminas_leidas: number;
}

/**
 * Detiene la lectura en el siguiente corte de lámina.
 *
 * NO corta al instante: una llamada de visión en vuelo no se puede abortar, así que la
 * lámina en curso termina. Lo que se acota es el desperdicio —una lámina en vez de las que
 * falten—. Lo leído se conserva y el mazo se puede reanudar: cancelar no es descartar.
 */
export async function cancelExtraction(
  slug: string, extractionId: string,
): Promise<CancelResult> {
  const { data } = await client.post(
    `${base}/engagements/${slug}/extractions/${extractionId}/cancel`);
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


/**
 * El tablero de ventas del operador. Idempotente por (encargo, fecha, local): reenviar la
 * misma entrega corrige las jornadas, no las duplica.
 */
export async function uploadSales(
  slug: string, file: File,
): Promise<SeriesUploadResult> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await client.post(`${base}/engagements/${slug}/sales`, form, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 2 * 60 * 1000,
  });
  return data;
}

/**
 * La matriz histórica del proveedor. Solo-si-falta: no sustituye una observación que ya
 * está, porque esa vino con su base muestral y la matriz no las trae.
 */
export async function uploadTrackerHistory(
  slug: string, file: File,
): Promise<SeriesUploadResult> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await client.post(
    `${base}/engagements/${slug}/tracker-history`, form, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 2 * 60 * 1000,
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
export type ReportFormat = "pdf" | "docx" | "html";

const REPORT_MIME: Record<ReportFormat, string> = {
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  html: "text/html",
};

export async function downloadReport(
  slug: string, fmt: ReportFormat = "pdf", wave?: string,
): Promise<void> {
  const { data } = await client.get(`${base}/engagements/${slug}/report.${fmt}`, {
    // Sin ola, el servidor mide la última con dato. El nombre del archivo lleva el corte
    // cuando se elige uno: dos informes del mismo encargo con distinta ola son documentos
    // distintos y no pueden compartir nombre en la carpeta de descargas.
    params: wave ? { wave } : undefined,
    responseType: "blob",
    // El PDF y el Word se arman en el servidor con el chrome de marca; un informe con
    // muchas olas y marcas tarda unos segundos.
    timeout: 3 * 60 * 1000,
  });
  const sufijo = wave ? `_${wave.replace(/[^\w-]/g, "")}` : "";
  triggerDownload(new Blob([data], { type: REPORT_MIME[fmt] }),
                  `SDQ-MIP_informe_contexto_${slug}${sufijo}.${fmt}`);
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

// ── conclusiones del proveedor y mesa de discrepancias ──────────────

export interface ProviderConclusion {
  id: string;
  claim: string;
  page_number: number;
  kind: "hallazgo" | "recomendacion" | "contexto";
  subjects: string[];
  subject_slugs: string[];
  topic: string | null;
  metric_code: string | null;
  direction: "sube" | "baja" | "estable" | null;
  wave_label: string | null;
  wave_code: string | null;
  confident: boolean;
  document: string | null;
}

export interface ConclusionsPayload {
  total: number;
  conclusions: ProviderConclusion[];
}

export type DiscrepancyStatus = "abierta" | "discutida" | "acordada" | "retirada";

export interface Discrepancy {
  id: string;
  claim: string;
  page_number: number;
  subject_slugs: string[];
  metric_code: string;
  provider_direction: string;
  data_note: string;
  per_brand: {
    brand: string;
    data_direction: string | null;
    delta: number | null;
    verdict: string;
    note: string;
  }[];
  status: DiscrepancyStatus;
  resolution_note: string | null;
  updated_by: string | null;
  created_at: string | null;
}

export interface DiscrepanciesPayload {
  total: number;
  bloqueantes: number;
  discrepancies: Discrepancy[];
}

export interface ContrastResult {
  conclusiones: number;
  coinciden: number;
  discrepan: number;
  no_evaluables: number;
  discrepancias_abiertas_ahora: { claim: string; page_number: number }[];
}

export async function getConclusions(slug: string): Promise<ConclusionsPayload> {
  const { data } = await client.get(`${base}/engagements/${slug}/conclusions`);
  return data;
}

export async function getDiscrepancies(slug: string): Promise<DiscrepanciesPayload> {
  const { data } = await client.get(`${base}/engagements/${slug}/discrepancies`);
  return data;
}

export async function runContrast(slug: string): Promise<ContrastResult> {
  const { data } = await client.post(`${base}/engagements/${slug}/contrast`);
  return data;
}

export async function downloadMesa(slug: string, fmt: "pdf" | "docx" = "pdf"): Promise<void> {
  const { data } = await client.get(`${base}/engagements/${slug}/mesa.${fmt}`, {
    responseType: "blob",
    timeout: 3 * 60 * 1000,
  });
  triggerDownload(new Blob([data], { type: REPORT_MIME[fmt] }),
                  `SDQ-MIP_nota_mesa_${slug}.${fmt}`);
}

export async function updateDiscrepancy(
  slug: string, id: string, status: DiscrepancyStatus, resolutionNote?: string,
): Promise<{ id: string; status: DiscrepancyStatus }> {
  const { data } = await client.patch(
    `${base}/engagements/${slug}/discrepancies/${id}`,
    { status, resolution_note: resolutionNote ?? null });
  return data;
}

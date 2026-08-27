import client from "@/shared/api/client";
import type { AiInsight } from "@/shared/ui/insight-types";

export interface CompareInsightItem {
  nombre: string;
  score: number | null;
  banda?: string;
  /** { label de dimensión: score } — solo cifras, las que ya están en pantalla. */
  dimensiones: Record<string, number>;
}

/**
 * Comparative AI insight (cross-axis). Sends the already-computed items (score +
 * dimension breakdown) to the transversal `/tools/compare-insight` endpoint, which
 * asks Claude for a SCQA comparison. Best-effort: returns null on failure.
 */
export async function getCompareInsight(
  eje: string,
  items: CompareInsightItem[],
): Promise<AiInsight | null> {
  const { data } = await client.post("/tools/compare-insight", { eje, items });
  return (data.ai_insight as AiInsight | null) ?? null;
}

/* ── Market Brief (síntesis cross-eje cacheada, generada por una Operación) ── */
export interface BriefAxis {
  eje: string;
  available: boolean;
  period?: string;
  headline?: string;
  score?: number | null;
  score_label?: string;
  band?: string | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  detail?: any;
}

export interface MarketBriefReport {
  computed: boolean;
  message?: string;
  snapshot?: { pais: string; axes: BriefAxis[] };
  brief?: AiInsight | null;
  n_ejes_con_dato?: number;
  generated_at?: string;
}

export async function getMarketBrief(): Promise<MarketBriefReport> {
  const { data } = await client.get("/tools/market-brief");
  return data;
}

/** Dispara la Operación market-brief (admin). Devuelve {started, reason?}. */
export async function runMarketBrief(): Promise<{ started: boolean; reason?: string }> {
  const { data } = await client.post("/operations/market-brief/run", {});
  return data;
}

/* ── Deal Scoring (rúbrica declarada anclada a los 7 ejes) ── */
export interface DealFactor {
  factor: string;
  value: number;
  source: string;
  weight: number;
  contribution: number;
}
export interface DealScoreResult {
  score: number;
  confidence: string;
  method: string;
  is_trained_model: boolean;
  key_factors: DealFactor[];
  components_present: number;
  components_total: number;
  anchors_used: Record<string, number>;
  anchor_sources: Record<string, string>;
  ai_insight: AiInsight | null;
}
export const DEAL_AUDIENCES = ["comite_inversion", "asesor", "promotor"] as const;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function scoreDeal(input: Record<string, any>): Promise<DealScoreResult> {
  const { data } = await client.post("/deal-scoring/score", input);
  return data;
}

export interface RetrospectiveDiagnostic {
  n: number;
  cv_auc: number;
  auc_ci: [number | null, number | null];
  note: string;
}
export interface LearningCurve {
  n_labeled: number;
  n_closed: number;
  n_lost: number;
  n_ex_ante: number;
  n_retrospective: number;
  computed: boolean;
  status: string; // "rubrica" | "modelo"
  ready_for_model: boolean;
  cv_auc?: number;
  auc_ci?: [number | null, number | null];
  graduation_floor: number;
  message: string;
  caveats?: string[];
  retrospective_diagnostic?: RetrospectiveDiagnostic | null;
}
export async function getLearningCurve(): Promise<LearningCurve> {
  const { data } = await client.get("/deal-scoring/learning-curve");
  return data;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function saveDeal(input: Record<string, any>): Promise<{ saved: boolean; total: number }> {
  const { data } = await client.post("/deal-scoring/deals", input);
  return data;
}

export async function importDeals(file: File): Promise<{ inserted: number; updated: number; skipped: number; total: number }> {
  const fd = new FormData();
  fd.append("file", file);
  const { data } = await client.post("/deal-scoring/import", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export interface DealRow {
  deal_name: string;
  deal_type: string | null;
  sector: string | null;
  country: string;
  deal_stage: string | null;
  closed_successfully: boolean | null;
  outcome_date: string | null;
  retrospective: boolean;
  label_confidence: string | null;
}
export interface DealRegistry {
  count: number;
  n_labeled: number;
  n_ex_ante: number;
  n_open: number;
  deals: DealRow[];
}
export async function getDeals(): Promise<DealRegistry> {
  const { data } = await client.get("/deal-scoring/deals");
  return data;
}

/** Cierra el lazo de cosecha: registra el desenlace de un deal ya en el registro.
 * `closed` true=cerró / false=se perdió. Preserva ex-ante/retrospectivo en el backend. */
export async function resolveOutcome(
  dealName: string,
  closed: boolean,
): Promise<{ resolved: boolean; closed_successfully: boolean; outcome_date: string; retrospective: boolean }> {
  const { data } = await client.patch(
    `/deal-scoring/deals/${encodeURIComponent(dealName)}/outcome`,
    { closed_successfully: closed },
  );
  return data;
}

/* ── Monitor de Productos (readiness + activación pública) ── */
export interface ProductLevel {
  tier: string; // "pulse" | "insight" | "deep_dive"
  readiness: number; // 0–1
  gates: { g1: number; g2: number; g3: number; g4: number; g5: number } | null;
  detail: Record<string, string> | null;
  threshold: number;
  can_activate: boolean;
  is_active: boolean;
  computed_at: string | null;
}
export interface ProductSector {
  sector_key: string;
  display_name: string;
  source: string;
  module_hint: string;
  implemented: boolean;
  levels: ProductLevel[];
}
export interface ProductMatrix {
  sectors: ProductSector[];
  thresholds: Record<string, number>;
}

export async function getProductReadiness(): Promise<ProductMatrix> {
  const { data } = await client.get("/products/readiness");
  return data;
}

export async function recomputeProductReadiness(): Promise<{ recomputed: number; matrix: ProductMatrix }> {
  const { data } = await client.post("/products/readiness/recompute");
  return data;
}

/* ── Readiness Audit (qué falta por eje + acción, exportable) ── */
export interface AuditGap {
  gate: string;
  label: string;
  value: number;
  weight: number;
  points_lost: number;
  lineage: string;
  falta: string;
  accion: string;
}
export interface AuditSector {
  sector_key: string;
  display_name: string;
  implemented: boolean;
  source: string;
  readiness: Record<string, number>;
  levels: { tier: string; readiness: number; threshold: number; can_publish: boolean }[];
  gaps: AuditGap[];
  headline: string;
}
export interface ReadinessAudit {
  generated_at: string;
  thresholds: Record<string, number>;
  summary: { full: string[]; pulse_only: string[]; blocked: string[]; pending: string[] };
  sectors: AuditSector[];
  markdown: string;
}

export async function getReadinessAudit(): Promise<ReadinessAudit> {
  const { data } = await client.get("/products/readiness/audit");
  return data;
}

export async function activateProduct(sector: string, tier: string): Promise<{ is_active: boolean }> {
  const { data } = await client.post(`/products/${sector}/${tier}/activate`);
  return data;
}

export async function deactivateProduct(sector: string, tier: string): Promise<{ is_active: boolean }> {
  const { data } = await client.post(`/products/${sector}/${tier}/deactivate`);
  return data;
}

/* ── Entitlements por-producto (monetización: compra/otorgamiento manual, admin) ── */
export interface UserEntitlement {
  id: string;
  user_id: string;
  sector_key: string;
  tier: string;
  source: string;
  granted_by: string | null;
  granted_at: string | null;
  expires_at: string | null;
  active: boolean;
  note: string | null;
}

export async function getUserEntitlements(userId: string): Promise<UserEntitlement[]> {
  const { data } = await client.get(`/products/entitlements/${encodeURIComponent(userId)}`);
  return data.entitlements as UserEntitlement[];
}

export async function grantEntitlement(input: {
  user_id: string; sector: string; tier: string; note?: string;
}): Promise<UserEntitlement> {
  const { data } = await client.post("/products/entitlements", input);
  return data as UserEntitlement;
}

export async function revokeEntitlement(id: string): Promise<void> {
  await client.post(`/products/entitlements/${encodeURIComponent(id)}/revoke`);
}

/* ── Suscripciones (aprovisionamiento manual por admin + "Mi plan" del usuario) ── */
export interface Subscription {
  id: string;
  user_id: string;
  provider: string;
  sku: string | null;
  interval: string | null;
  tier: string;
  status: string;
  current_period_end: string | null;
  started_at: string | null;
  cancelled_at: string | null;
  note: string | null;
}

export async function getUserSubscriptions(userId: string): Promise<Subscription[]> {
  const { data } = await client.get(`/products/subscriptions/${encodeURIComponent(userId)}`);
  return data.subscriptions as Subscription[];
}

/** Alta o cambio de plan de la suscripción manual del usuario (admin). */
export async function setSubscription(input: {
  user_id: string; sku?: string; tier?: string; interval?: string;
  current_period_end?: string | null; note?: string;
}): Promise<Subscription> {
  const { data } = await client.post("/products/subscriptions", input);
  return data as Subscription;
}

export async function cancelSubscription(id: string): Promise<void> {
  await client.post(`/products/subscriptions/${encodeURIComponent(id)}/cancel`);
}

export interface MyPlan {
  manual_tier: string;
  subscription_tier: string | null;
  effective_tier: string;
  subscriptions: Subscription[];
  entitlements: UserEntitlement[];
}

/** El plan del usuario autenticado (tier efectivo + suscripción + accesos por-producto). */
export async function getMyPlan(): Promise<MyPlan> {
  const { data } = await client.get("/products/me/plan");
  return data as MyPlan;
}

/* ── Catálogo de consumo (monetización: solo niveles publicados, con estado de
 *    acceso resuelto por el backend según el tier del usuario) ── */
export interface CatalogLevel {
  tier: string; // "pulse" | "insight" | "deep_dive"
  unlocked: boolean; // el tier del usuario alcanza este nivel (o vista interna de staff)
  /** Desbloqueado por ser staff interno (super_admin), no por compra/tier del cliente. */
  staff_preview: boolean;
  required_tier: string; // "free" | "pro" | "enterprise"
  price_band: string | null;
  audience: string;
  /** Solo en niveles bloqueados: muestra demo disponible (no descargada aún). */
  sample_available: boolean;
  /** El nivel nombrado necesita que el usuario ELIJA un sujeto. Los productos de sujeto
   *  fijo (sector nacional) cargan directo, sin pedir nada. */
  requires_scope: boolean;
  /** Qué se elige cuando requires_scope: "entity" (banco) | "country" (país, panel). */
  scope_kind: string;
}
export interface CatalogSector {
  sector_key: string;
  display_name: string;
  levels: CatalogLevel[];
  /** Clave del producto HERMANO cuya unidad es el AÑO, si el manifiesto lo declara y ese
   *  producto está publicado para este usuario. `null` si no hay. Lo declara el backend a
   *  propósito: cablear la pareja acá haría que un anual nuevo (seguros, pensiones) no
   *  apareciera solo. */
  annual_companion?: string | null;
}
export interface ProductCatalog {
  sectors: CatalogSector[];
  user_tier: string;
}

export async function getProductCatalog(): Promise<ProductCatalog> {
  const { data } = await client.get("/products/catalog");
  return data;
}

/** Contenido in-app de un producto (gateado por tier+activación en el backend). */
export interface ProductReport {
  sector_key: string;
  tier: string;
  period: string | null;
  entity_name: string | null;
  payload: Record<string, unknown>;
  narratives: Record<string, string>;
  commercial: {
    price_band: string | null;
    watermark: string | null;
    audience: string;
    cadence: string;
    sections: string[];
    staff_preview: boolean;
  };
}

/** Dimensión normalizada para el gráfico online (key i18n + score 0–100, o label crudo). */
export interface ReportDimension {
  key: string;
  score: number;
  label?: string; // si la fuente ya trae un label humano (p.ej. pension)
}

/**
 * Extrae las dimensiones puntuadas del `payload` del reporte para el gráfico online,
 * tolerando las distintas formas por producto (index.dimensions · score.breakdown ·
 * latest.iai_breakdown · dimensions · rating.dimensions[]). Best-effort: devuelve []
 * si no hay un set claro de dimensiones (p.ej. trade / pulse de pensiones).
 */
export function reportDimensions(report: ProductReport): ReportDimension[] {
  const p = (report.payload ?? {}) as Record<string, any>;
  const out: ReportDimension[] = [];
  const pushObj = (dims: unknown) => {
    if (!dims || typeof dims !== "object") return;
    for (const [k, d] of Object.entries(dims as Record<string, any>)) {
      const s = d?.score;
      if (typeof s === "number") out.push({ key: k, score: s });
    }
  };
  if (p.index?.dimensions) pushObj(p.index.dimensions);
  else if (p.score?.breakdown?.dimensions) pushObj(p.score.breakdown.dimensions);
  else if (p.latest?.iai_breakdown) pushObj(p.latest.iai_breakdown);
  else if (p.dimensions) pushObj(p.dimensions);
  else if (Array.isArray(p.rating?.dimensions)) {
    for (const d of p.rating.dimensions as any[]) {
      if (typeof d?.score === "number") out.push({ key: d.label ?? "", score: d.score, label: d.label });
    }
  }
  return out;
}

/** El aporte de un componente dentro de una ventana. */
export interface AporteComponente {
  componente: string;
  delta_score: number | null;
  peso: number | null;
  aporte_al_cambio: number | null;
}

/** «Qué movió el score» en una ventana: trimestre, semestre o año. */
export interface VentanaDeCambio {
  ventana: string;
  /** Los aportes de la ventana SUMAN esto — es lo que vuelve auditable la atribución. */
  cambio_total: number | null;
  aportes: AporteComponente[];
  principal: string | null;
  cuota_del_principal_pct: number | null;
  lectura: string | null;
}

/**
 * La atribución del cambio del score, del payload del reporte.
 *
 * Se LEE, no se computa: la cuenta ya la hizo el backend con los pesos del TIPO de entidad
 * (`shared.narrative.derived.aportes_al_cambio`). Recomputarla acá sería una segunda
 * implementación de la misma cuenta y una segunda oportunidad de que discrepen — y la
 * dimensión que más se movió NO es la que más movió el resultado, porque los pesos difieren.
 * Un informe entregado atribuyó el deterioro de un semestre al «colapso de eficiencia»
 * cuando en ese semestre la eficiencia MEJORÓ.
 *
 * Vivía solo en el PDF: el mismo Deep Dive mostraba la tabla al descargarlo y no al verlo.
 */
export function reportAportes(report: ProductReport): VentanaDeCambio[] {
  const filas = (report.payload as any)?.scoring_result?.aportes_al_cambio;
  if (!Array.isArray(filas)) return [];
  return filas
    .filter((f) => f && typeof f.ventana === "string" && Array.isArray(f.aportes))
    .map((f) => ({
      ventana: f.ventana as string,
      cambio_total: typeof f.cambio_total === "number" ? f.cambio_total : null,
      aportes: (f.aportes as any[])
        .filter((a) => a && typeof a.componente === "string")
        .map((a) => ({
          componente: a.componente as string,
          delta_score: typeof a.delta_score === "number" ? a.delta_score : null,
          peso: typeof a.peso === "number" ? a.peso : null,
          aporte_al_cambio:
            typeof a.aporte_al_cambio === "number" ? a.aporte_al_cambio : null,
        })),
      principal: typeof f.principal === "string" ? f.principal : null,
      cuota_del_principal_pct:
        typeof f.cuota_del_principal_pct === "number" ? f.cuota_del_principal_pct : null,
      lectura: typeof f.lectura === "string" ? f.lectura : null,
    }));
}

/**
 * Los componentes que aparecen, en el orden en que el backend los sirvió.
 *
 * No se ordenan alfabéticamente ni por magnitud: el backend ya los ordena, y reordenar acá
 * haría que la pantalla y el PDF listaran lo mismo en distinto orden.
 */
export function componentesDeAportes(ventanas: VentanaDeCambio[]): string[] {
  const vistos: string[] = [];
  for (const v of ventanas) {
    for (const a of v.aportes) if (!vistos.includes(a.componente)) vistos.push(a.componente);
  }
  return vistos;
}

/**
 * ¿Este corte cae en el CIERRE DEL EJERCICIO (31 de diciembre)? Devuelve el año, o `null`.
 *
 * **Para qué sirve, y para qué NO.** Sirve para OFRECER el producto anual desde el selector
 * trimestral. NO sirve para rotular el corte de diciembre como si fuera el informe del año:
 * esa fue exactamente la afirmación que el dueño refutó, y este archivo la sostuvo por
 * escrito («no hay —ni debe haber— un SKU informe anual aparte») mientras el backend ya
 * servía el producto anual. El resultado en pantalla fue que el cuarto trimestre pareció
 * DESAPARECER, sustituido por un «cierre anual» que no entrega el año.
 *
 * Por qué es falso: la ventana móvil de doce meses toca UNA magnitud —la utilidad neta, o
 * sea ROA y ROE—; los otros diecinueve indicadores son fotos al 31 de diciembre y el score
 * es una lectura AL CORTE. El informe de diciembre dice cómo ESTÁ la entidad ese día; cómo
 * le FUE en el ejercicio lo dice `banking_year_review`, que es un producto aparte, está en
 * producción y se pide por AÑO (`2025`), no por fecha.
 *
 * Diciembre es un corte trimestral como los otros tres, y se rotula como tal.
 */
export function cierreDeEjercicio(periodEnd: string): string | null {
  const m = /^(\d{4})-12-31$/.exec(periodEnd);
  return m ? m[1] : null;
}

/** Una entrada del selector de períodos: qué producto la sirve y con qué período. */
export interface OpcionDePeriodo {
  /** Valor del `<option>`; único entre las dos familias. */
  value: string;
  /** Producto que atiende esta lectura. */
  sector: string;
  /** Período tal como lo espera ese producto: `2025-12-31` o `2025`. */
  period: string;
  /** ¿Es la lectura del AÑO? Cambia el encabezado del panel. */
  esAnual: boolean;
}

/** El año de un período, sea corte (`2025-12-31`) o año (`2025`). `null` si no se reconoce. */
function anioDe(periodo: string): number | null {
  const m = /^(\d{4})/.exec(periodo);
  return m ? Number(m[1]) : null;
}

/**
 * Separa el calendario de un producto en AÑOS y CORTES, y los ordena por año.
 *
 * **Por qué el año lo sirve el MISMO producto.** Al principio el año se enrutaba al producto
 * anual, y el resultado fue que los dos servían el mismo informe. El dueño lo separó el
 * 2026-08-27: dentro de «SDQ Banking Intelligence» el año se lee POR DENTRO —la serie de sus
 * trimestres y el movimiento de cada tramo—; el año contra los años anteriores y la tendencia
 * son «SDQ Banking · Revisión Anual», otra tarjeta del catálogo.
 *
 * Así que no hay ruteo cruzado: cada opción se le pide al producto que se está mirando. Eso
 * además arregla el encabezado, que decía «Revisión Anual» sobre un título que decía
 * «Intelligence» — la contradicción era el síntoma del ruteo.
 *
 * Orden: por año descendente y, dentro de cada año, el AÑO primero y después sus cortes — la
 * lectura más general antes que sus partes. Un período que no empiece por cuatro dígitos se
 * conserva al final en su orden original: no se descarta lo que no se entiende.
 */
export function fusionarPeriodos(sector: string, periodos: string[]): OpcionDePeriodo[] {
  const esAnio = (p: string) => /^\d{4}$/.test(p);
  const opcion = (p: string): OpcionDePeriodo =>
    ({ value: p, sector, period: p, esAnual: esAnio(p) });

  const porAnio = new Map<number, OpcionDePeriodo[]>();
  const sinAnio: OpcionDePeriodo[] = [];
  for (const p of periodos) {
    const a = anioDe(p);
    if (a === null) { sinAnio.push(opcion(p)); continue; }
    const previas = porAnio.get(a) || [];
    porAnio.set(a, esAnio(p) ? [opcion(p), ...previas] : [...previas, opcion(p)]);
  }
  const anios = [...porAnio.keys()].sort((x, y) => y - x);
  return [...anios.flatMap((a) => porAnio.get(a)!), ...sinAnio];
}

/**
 * El informe in-app de un producto.
 *
 * *signal* permite ABORTAR la petición. No es un lujo: una generación real de un Deep Dive
 * tarda ~100 s, y cambiar de período mientras corre encendía otra sin apagar la anterior —
 * tres generaciones simultáneas del mismo informe, cobradas las tres, entregada ninguna.
 * Quien llame desde una pantalla que puede cambiar de sujeto TIENE que pasarlo.
 */
export async function getProductReport(
  sector: string,
  tier: string,
  opts: { period?: string; scope?: string } = {},
  signal?: AbortSignal,
): Promise<ProductReport> {
  const { data } = await client.get(`/products/${sector}/${tier}/report`,
                                    { params: opts, signal });
  return data;
}

/** ¿Este error es una petición que NOSOTROS abortamos? Axios la rechaza como cualquier
 *  otra, y mostrarla como fallo pondría un cartel de error por haber cambiado de período. */
export function esAbortada(e: unknown): boolean {
  const err = e as { code?: string; name?: string };
  return err?.code === "ERR_CANCELED" || err?.name === "CanceledError"
    || err?.name === "AbortError";
}

/** Entidad elegible de un nivel nombrado (alimenta el selector del catálogo). */
export interface ScopeOption {
  value: string; // id o nombre que acepta el backend como scope
  label: string; // visible
  group?: string; // agrupador (p.ej. tipo de entidad)
}

/** Entidades elegibles de los niveles nombrados de un sector. Vacío si el sector no las
 *  expone (el catálogo cae al input libre). */
export async function getProductScopeOptions(sector: string): Promise<ScopeOption[]> {
  const { data } = await client.get(`/products/${sector}/scope-options`);
  return data.options ?? [];
}

/** Períodos reales del producto (más reciente primero) para el selector del reporte.
 * Vacío si el producto no los expone → el front cae al período global. */
export async function getProductPeriods(sector: string): Promise<string[]> {
  const { data } = await client.get(`/products/${sector}/periods`);
  return data.periods ?? [];
}

/** Dispara la descarga de un blob PDF de `url` (con auth vía interceptor). */
async function downloadPdfBlob(url: string, fallback: string, params = {}): Promise<void> {
  const r = await client.get(url, { params, responseType: "blob" });
  const cd = (r.headers["content-disposition"] as string) || "";
  const filename = /filename="?([^"]+)"?/.exec(cd)?.[1] ?? fallback;
  const blobUrl = URL.createObjectURL(r.data as Blob);
  const a = document.createElement("a");
  a.href = blobUrl;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(blobUrl);
}

/** Descarga el reporte del producto en PDF o Word (mismo gate que la vista in-app). */
export async function downloadProductReport(
  sector: string,
  tier: string,
  fmt: "pdf" | "docx" = "pdf",
  opts: { period?: string; scope?: string } = {},
): Promise<void> {
  await downloadPdfBlob(`/products/${sector}/${tier}/download`,
    `SDQ_${sector}_${tier}.${fmt}`, { ...opts, format: fmt });
}

/** Atajo PDF (compat). */
export async function downloadProductPdf(
  sector: string,
  tier: string,
  opts: { period?: string; scope?: string } = {},
): Promise<void> {
  await downloadProductReport(sector, tier, "pdf", opts);
}

/** Descarga la muestra demo (una vez por sector/nivel; 409 si ya se descargó). */
export async function downloadProductSample(sector: string, tier: string): Promise<void> {
  await downloadPdfBlob(`/products/${sector}/${tier}/sample`, `SDQ_muestra_${sector}_${tier}.pdf`);
}

/* ── Motor de Research Custom (pregunta libre → informe con procedencia) ── */
export type AnchorState = "real" | "rubric" | "gap";

export interface ResearchEvidence {
  text: string;
  source: string;
  kind: string;
  state: AnchorState;
  score: number;
  ref?: string;
}
export interface ResearchSubQuestion {
  text: string;
  state: AnchorState;
  anchored: boolean;
  axes: string[];
  note?: string;
  evidence: ResearchEvidence[];
}
export interface ResearchGap {
  sub_question: string;
  note: string;
  candidate_source?: string | null;
}
export interface ResearchAnswer {
  question: string;
  gate: "report" | "scoping";
  coverage_real: number;
  anchored_fraction: number;
  state_counts: Record<AnchorState, number>;
  sub_questions: ResearchSubQuestion[];
  sections: Record<string, string>;
  section_order: string[];
  sources: string[];
  gaps: ResearchGap[];
  generated_at: string;
  markdown?: string;
}

/** Corre el motor sobre una pregunta libre y devuelve la respuesta con procedencia. */
export async function runResearch(
  question: string,
  opts: { gap_threshold?: number; per_q_k?: number; min_anchor_score?: number } = {},
): Promise<ResearchAnswer> {
  const { data } = await client.post("/research", { question, ...opts });
  return data as ResearchAnswer;
}

/** Descarga el entregable de marca (PDF/Word) de una pregunta. */
export async function downloadResearchDeliverable(
  question: string,
  fmt: "pdf" | "docx" = "pdf",
): Promise<void> {
  const r = await client.post(
    "/research/deliverable",
    { question, fmt },
    { responseType: "blob" },
  );
  const cd = (r.headers["content-disposition"] as string) || "";
  const filename =
    /filename="?([^"]+)"?/.exec(cd)?.[1] ?? `SDQ_research.${fmt}`;
  const blobUrl = URL.createObjectURL(r.data as Blob);
  const a = document.createElement("a");
  a.href = blobUrl;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(blobUrl);
}

/**
 * El nombre CORTO de un producto, para rotular una opción dentro de otro producto.
 *
 * Los nombres del catálogo llevan la familia adelante («SDQ Banking · Revisión Anual») y
 * repetirla dentro del selector de esa misma familia es ruido: la opción quedaría «2025 ·
 * SDQ Banking · Revisión Anual» dentro del panel de SDQ Banking. Se toma el último tramo.
 *
 * Se DERIVA del nombre declarado en vez de escribirlo acá: el día que exista un anual de
 * seguros, su opción se rotula sola. Una constante en la pantalla se desincroniza del
 * catálogo y nadie se entera — es el defecto de las etiquetas duplicadas de tipo de entidad,
 * que ya nos costó dos formas distintas del mismo estrato.
 */
export function nombreCortoDeProducto(displayName: string): string {
  const tramos = displayName.split("\u00b7").map((x) => x.trim()).filter(Boolean);
  return tramos.length > 1 ? tramos[tramos.length - 1] : displayName.trim();
}

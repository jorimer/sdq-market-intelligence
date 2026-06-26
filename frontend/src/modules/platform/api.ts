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

/* ── Catálogo de consumo (monetización: solo niveles publicados, con estado de
 *    acceso resuelto por el backend según el tier del usuario) ── */
export interface CatalogLevel {
  tier: string; // "pulse" | "insight" | "deep_dive"
  unlocked: boolean; // el tier del usuario alcanza este nivel
  required_tier: string; // "free" | "pro" | "enterprise"
  price_band: string | null;
  audience: string;
  /** Solo en niveles bloqueados: muestra demo disponible (no descargada aún). */
  sample_available: boolean;
}
export interface CatalogSector {
  sector_key: string;
  display_name: string;
  levels: CatalogLevel[];
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
  };
}

export async function getProductReport(
  sector: string,
  tier: string,
  opts: { period?: string; scope?: string } = {},
): Promise<ProductReport> {
  const { data } = await client.get(`/products/${sector}/${tier}/report`, { params: opts });
  return data;
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

/** Descarga el PDF del producto (respeta el mismo gate que la vista in-app). */
export async function downloadProductPdf(
  sector: string,
  tier: string,
  opts: { period?: string; scope?: string } = {},
): Promise<void> {
  await downloadPdfBlob(`/products/${sector}/${tier}/download`, `SDQ_${sector}_${tier}.pdf`, opts);
}

/** Descarga la muestra demo (una vez por sector/nivel; 409 si ya se descargó). */
export async function downloadProductSample(sector: string, tier: string): Promise<void> {
  await downloadPdfBlob(`/products/${sector}/${tier}/sample`, `SDQ_muestra_${sector}_${tier}.pdf`);
}

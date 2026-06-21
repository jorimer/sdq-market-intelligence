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
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function scoreDeal(input: Record<string, any>): Promise<DealScoreResult> {
  const { data } = await client.post("/deal-scoring/score", input);
  return data;
}

export interface LearningCurve {
  n_labeled: number;
  n_closed: number;
  n_lost: number;
  computed: boolean;
  status: string; // "rubrica" | "modelo"
  ready_for_model: boolean;
  cv_auc?: number;
  auc_ci?: [number | null, number | null];
  graduation_floor: number;
  message: string;
  caveats?: string[];
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

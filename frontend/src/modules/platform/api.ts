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

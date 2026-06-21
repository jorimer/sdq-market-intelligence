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

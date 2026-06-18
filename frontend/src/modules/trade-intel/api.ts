import client from "@/shared/api/client";

export interface TopProduct {
  product: string;
  value: number;
  share: number;
}

/** Persisted trade-resilience score (real DGA customs data), or has_score=false. */
export interface TradeScore {
  has_score: boolean;
  period?: string;
  hhi_exports: number | null;
  export_diversification: number | null;
  import_dependency: number | null;
  resilience_score: number | null;
  total_exports: number | null;
  total_imports: number | null;
  top_export_products: TopProduct[];
  n_products_export: number | null;
  n_products_import: number | null;
  source?: string;
}

export async function getTradeScore(): Promise<TradeScore> {
  const { data } = await client.get("/trade-intel/score");
  return data;
}

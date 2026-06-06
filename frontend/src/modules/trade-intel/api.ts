import client from "@/shared/api/client";

export interface TopProduct {
  product: string;
  value: number;
  share: number;
}

export interface TradeScore {
  hhi_exports: number | null;
  export_diversification: number | null;
  import_dependency: number | null;
  resilience_score: number | null;
  total_exports: number;
  total_imports: number;
  top_export_products: TopProduct[];
  n_products_export: number;
  n_products_import: number;
}

export interface Flow {
  product: string;
  direction: "export" | "import";
  value: number;
  partner?: string;
}

export async function scoreTrade(flows: Flow[]): Promise<TradeScore> {
  const { data } = await client.post("/trade-intel/score", { flows });
  return data;
}

export async function saveSnapshot(period: string, flows: Flow[]) {
  const { data } = await client.post("/trade-intel/snapshot", { period, flows });
  return data as TradeScore & { period: string; score_id: string };
}

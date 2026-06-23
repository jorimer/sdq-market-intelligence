import client from "@/shared/api/client";
import type { AiInsight } from "@/shared/ui/insight-types";

export const TRADE_AUDIENCES = ["exportador", "gobierno", "inversionista"] as const;

/** Contextual AI insight for the trade-resilience picture, oriented by audience. */
export async function getTradeInsight(
  audience: string = TRADE_AUDIENCES[0],
): Promise<AiInsight | null> {
  const { data } = await client.get("/trade-intel/insight", { params: { audience } });
  return (data.ai_insight as AiInsight | null) ?? null;
}

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

// ── Backtest (Gate E) ──────────────────────────────────────────
export interface BacktestMetrics {
  n_observations: number;
  n_events: number;
  event_rate: number | null;
  years: [number, number] | null;
  gini: number | null;
  gini_ci: [number | null, number | null];
  distress_by_band: { tier: string; n: number; events: number; rate: number | null }[];
  monotonic: boolean;
}

export interface TradeBacktestReport {
  has_report: boolean;
  primary_outcome?: string;
  n_countries?: number;
  coverage?: {
    panel_size: number;
    countries_in_panel: string[];
    missing: string[];
    years: [number, number] | null;
  };
  export_collapse?: BacktestMetrics;  // PRIMARY — construct the index targets
  external_macro?: BacktestMetrics;   // SECONDARY — independent contrast (null)
  disclaimer?: string;
  generated_at?: string;
}

export async function getTradeBacktest(): Promise<TradeBacktestReport> {
  const { data } = await client.get("/trade-intel/validation/backtest");
  return data;
}

export async function runTradeBacktest(): Promise<{ started: boolean; reason?: string }> {
  const { data } = await client.post("/operations/trade-backtest/run", {});
  return data;
}

// ── Partner-country concentration (geographic resilience) ──────
export interface PartnerBlock {
  total: number;
  hhi: number | null;
  diversification: number | null;
  n_partners: number;
  top: { partner: string; value: number; share: number }[];
}

export interface TradePartners {
  has_data: boolean;
  period?: string;
  source?: string;
  export?: PartnerBlock;
  import?: PartnerBlock;
}

export async function getTradePartners(): Promise<TradePartners> {
  const { data } = await client.get("/trade-intel/partners");
  return data;
}

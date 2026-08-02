import client from "@/shared/api/client";
import type { AiInsight } from "@/shared/ui/insight-types";

export interface IRMPDimension {
  score: number;
  weight: number;
  contribution: number;
  variables: Record<string, { raw: number; normalized: number; inverted: boolean }>;
}

export interface IRMPResult {
  country_code: string;
  irmp_score: number;
  risk_band: string;
  band_color: string;
  dimensions: Record<string, IRMPDimension>;
  peer_set_size: number;
  model_version: string;
  ai_insight?: AiInsight | null;
}

export interface IRMPWeights {
  dimension_weights: Record<string, number>;
  dimension_variables: Record<string, string[]>;
  risk_increasing_variables: string[];
  direction: string;
}

type RegionalDataset = Record<string, Record<string, number>>;

export async function getWeights(): Promise<IRMPWeights> {
  const { data } = await client.get("/macro-political-risk/weights");
  return data;
}

export interface IrmpDataset {
  period: string | null;
  dataset: Record<string, Record<string, number>>;
  sources: Record<string, Record<string, "live" | "rubric">>;
  has_live: boolean;
}

// Full assembled dataset (declared rubric overlaid with live data) + provenance.
// Single source of truth so the UI scores exactly what the snapshot persists.
export async function getDataset(period?: string): Promise<IrmpDataset> {
  const { data } = await client.get("/macro-political-risk/dataset", {
    params: period ? { period } : undefined,
  });
  return data;
}

export const MPR_AUDIENCES = [
  "inversionista",
  "gobierno",
  "multilateral",
  "empresa",
] as const;

export async function scoreCountry(
  countryCode: string,
  dataset: RegionalDataset,
  opts?: { withAi?: boolean; countryName?: string; audience?: string; deep?: boolean },
): Promise<IRMPResult> {
  const { data } = await client.post(
    "/macro-political-risk/score",
    { country_code: countryCode, dataset, country_name: opts?.countryName },
    { params: opts?.withAi ? { with_ai: true, audience: opts.audience, ...(opts.deep ? { deep: true } : {}) } : undefined },
  );
  return data;
}

export async function saveSnapshot(
  countryCode: string,
  dataset: RegionalDataset,
  periodEnd: string,
  countryName?: string,
): Promise<IRMPResult & { snapshot_id: string }> {
  const { data } = await client.post("/macro-political-risk/snapshot", {
    country_code: countryCode,
    dataset,
    period_end: periodEnd,
    country_name: countryName,
  });
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

export interface BacktestReport {
  has_report: boolean;
  primary_outcome?: string;
  n_countries?: number;
  governance?: BacktestMetrics;
  credit?: BacktestMetrics;
  convergent_validity?: {
    spearman_irmp_vs_rating: number | null;
    pairs: { iso: string; irmp: number; rating: string; rating_score: number }[];
  };
  disclaimer?: string;
  generated_at?: string;
}

export async function getBacktest(): Promise<BacktestReport> {
  const { data } = await client.get("/macro-political-risk/validation/backtest");
  return data;
}

export async function runBacktest(): Promise<{ started: boolean; reason?: string }> {
  const { data } = await client.post("/operations/irmp-backtest/run", {});
  return data;
}

/* ── Panel soberano (multi-agencia) + anotación de afirmación ── */

export interface SovereignAgencyRow {
  agency: string;
  name: string;
  rating: string;
  outlook: string | null;
  action_date: string | null;
  affirm_date: string | null;
  score: number | null;
  is_anchor: boolean;
}

export interface SovereignCountry {
  iso: string;
  in_store: boolean; // solo lo sincronizado admite anotación (el piso yaml va por PR)
  stale: boolean;
  agencies: SovereignAgencyRow[];
}

export interface SovereignPanel {
  countries: SovereignCountry[];
  anchor_agency: string;
  anchor_name: string;
  stale_after_months: number;
  store_source: string | null;
  store_fetched_at: string | null;
  can_annotate: boolean;
}

export async function getSovereignPanel(): Promise<SovereignPanel> {
  const { data } = await client.get("/macro-political-risk/sovereign-panel");
  return data;
}

export async function affirmSovereignRating(
  iso: string,
  affirmDate: string,
  agency?: string,
): Promise<void> {
  await client.post(
    `/macro-political-risk/sovereign-panel/${encodeURIComponent(iso)}/affirm`,
    { affirm_date: affirmDate, ...(agency ? { agency } : {}) },
  );
}

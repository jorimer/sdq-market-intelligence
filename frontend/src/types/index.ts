/* ── Banking Score domain types ─────────────────────────────────── */

export interface SubComponents {
  solidez: number;
  calidad: number;
  eficiencia: number;
  liquidez: number;
  diversificacion: number;
}

export interface IndicatorDetail {
  raw: number;
  score: number;
}

export interface ScoringResult {
  overall_score: number;
  rating_tier: string;
  tier_color: string;
  sub_components: SubComponents;
  indicators: Record<string, IndicatorDetail>;
  model_type: string;
  model_version: string;
}

export interface RatingAction {
  id: number;
  bank_name: string;
  period: string;
  overall_score: number;
  rating_tier: string;
  previous_tier: string | null;
  action_type: string;
  outlook: string;
  analyst: string;
  created_at: string;
}

export interface RankingEntry {
  bank_name: string;
  period: string;
  overall_score: number;
  rating_tier: string;
  tier_color: string;
  sub_components: SubComponents;
  rank: number;
  change: number;
}

export interface ModelStatus {
  ml_available: boolean;
  model_type: string;
  model_version: string;
  model_metrics: {
    accuracy: number;
    kappa: number;
    n_train: number;
    n_test: number;
  } | null;
  training_records: number;
  total_ratings: number;
  min_records_for_training: number;
  can_train: boolean;
}

export interface DataPeriod {
  id: number;
  bank_name: string;
  period: string;
  created_at: string;
}

export interface DataStats {
  total_records: number;
  total_banks: number;
  periods: string[];
  latest_period: string | null;
}

export interface ReportEntry {
  id: number;
  report_type: string;
  bank_name: string;
  period: string;
  file_path: string;
  created_at: string;
}

export interface BenchmarkData {
  sector_averages: Record<string, number>;
  peer_groups: Record<string, { members: string[]; averages: Record<string, number> }>;
  regulatory_limits: Record<string, number>;
}

export interface ScenarioInput {
  solidez: number;
  calidad: number;
  eficiencia: number;
  liquidez: number;
  diversificacion: number;
}

export interface ComparisonBank {
  bank_name: string;
  scoring_result: ScoringResult;
}

/* ── Auth types ───────────────────────────────────────────────── */

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user_id: string;
  email: string;
  full_name: string;
  role: string;
}

/* ── API response wrappers ────────────────────────────────────── */

export interface ApiError {
  detail: string;
}

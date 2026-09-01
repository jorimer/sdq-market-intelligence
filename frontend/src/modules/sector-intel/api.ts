import client from "@/shared/api/client";
import type { AiInsight } from "@/shared/ui/insight-types";

export const SECTOR_AUDIENCES = [
  "inversionista",
  "empresa",
  "financiador",
  "formulador_politica",
] as const;

/** Contextual AI insight for one sector (IAI/SGPS narrative), oriented by audience.
 * Best-effort. */
export async function getSectorInsight(
  sectorCode: string,
  audience: string = SECTOR_AUDIENCES[0],
  deep = false,
): Promise<AiInsight | null> {
  const { data } = await client.get(`/sector-intel/${sectorCode}/insight`, {
    params: { audience, ...(deep ? { deep: true } : {}) },
  });
  return (data.ai_insight as AiInsight | null) ?? null;
}

export interface SectorSummary {
  sector_code: string;
  iai_score: number;
  iai_band: string;
  sgps_score: number;
}

export interface AccelerationDetail {
  acceleration: number;
  base: number;
  components: Record<string, number>;
  inputs_present: string[];
}

export interface SnapshotResult {
  period: string;
  country_code: string;
  acceleration: AccelerationDetail;
  sectors: SectorSummary[];
  model_version: string;
}

export interface SectorLatest {
  has_score: boolean;
  sector_code: string;
  period: string;
  iai_score: number;
  iai_band: string;
  sgps_score: number;
  iai_breakdown: Record<
    string,
    { score: number; weight: number; contribution: number }
  >;
  sgps_breakdown: {
    sgps_score: number;
    factors: Record<string, { value: number; weight: number; contribution: number; imputed: boolean }>;
    acceleration_detail?: AccelerationDetail;
  };
}

type Dataset = Record<string, Record<string, number>>;
type SgpsInputs = Record<string, Record<string, number>>;

export async function getWeights() {
  const { data } = await client.get("/sector-intel/weights");
  return data as {
    iai_dimension_weights: Record<string, number>;
    sgps_weights: Record<string, number>;
    direction: string;
  };
}

export async function snapshot(
  period: string,
  dataset: Dataset,
  sgpsInputs: SgpsInputs,
): Promise<SnapshotResult> {
  const { data } = await client.post("/sector-intel/snapshot", {
    period,
    dataset,
    sgps_inputs: sgpsInputs,
  });
  return data;
}

export async function getLatest(sectorCode: string): Promise<SectorLatest> {
  const { data } = await client.get(`/sector-intel/${sectorCode}/latest`);
  return data;
}

// ── Macro→sectorial contract (§2 "Contexto macro") — produced by Eje 2 ──
export interface MacroFactor {
  key: string;
  label: string;
  value: number | null;
  unit: string | null;
  direction: "favorable" | "adverso" | "neutral" | "n/d";
  magnitude: "alto" | "moderado" | "bajo" | "n/d";
  reading: string;
  impacted_sectors: { slug: string; name: string }[];
  impacted_agents: string[];
  trend: string | null;
  series_code: string | null;
  rationale: string;
}

export interface MacroContext {
  period: string | null;
  factors: MacroFactor[];
  factor_count: number;
  available_count: number;
  generated_from: string;
  doctrine_version: string | null;
}

export async function getMacroContext(period?: string): Promise<MacroContext> {
  const { data } = await client.get("/macro-monitor/macro-context", {
    params: period ? { period } : undefined,
  });
  return data;
}

export interface SectorInfo {
  code: string;
  name: string;
  is_active: boolean;
}

export async function getSectors(): Promise<SectorInfo[]> {
  const { data } = await client.get("/sector-intel/sectors");
  return data.sectors as SectorInfo[];
}

export interface IaiDataset {
  period: string | null;
  dataset: Record<string, Record<string, number>>;
  sources: Record<string, Record<string, "live" | "rubric">>;
  sgps_inputs: Record<string, Record<string, number>>;
  has_live: boolean;
}

export async function getDataset(): Promise<IaiDataset> {
  const { data } = await client.get("/sector-intel/dataset");
  return data;
}

// ── Gate E (validación: IAI_T vs Δempleo formal T+1) ─────────────
export interface GateEByYear {
  year: string;
  n: number;
  spearman: number | null;
}
export interface GateEQuintileSpread {
  top_iai_mean_growth: number;
  bottom_iai_mean_growth: number;
  spread: number;
  n_years: number;
}
/** Un desenlace del Gate E, con su control por tamaño cuando lo tiene. */
export interface SectorGateEOutcome {
  que_mide?: string;
  resolucion?: string;
  mean_yearly_ic?: number | null;
  ic_ci?: [number | null, number | null];
  n_observations?: number;
  n_years?: number;
  conclusive?: boolean;
  invertido?: boolean;
  contraste_nivel?: SectorGateEOutcome | null;
  nota_contraste?: string;
  nota_control?: string;
  /** `intensidad` califica al desenlace primario; `nivel`, al contraste. Un IC sin su
   *  control no se renderiza: sin él, «el índice ordena» y «el tamaño ordena y el índice lo
   *  copia» son indistinguibles. */
  control_solo_tamano?: {
    intensidad?: SectorGateEControl | null;
    nivel?: SectorGateEControl | null;
  } | null;
}

export interface SectorGateEControl {
  mean_yearly_ic?: number | null;
  ic_ci?: [number | null, number | null];
  n_observations?: number;
  veredicto?: string;
  empata_con_el_score?: boolean;
  el_tamano_alcanza_al_score?: boolean;
}

export interface SectorGateEReport {
  has_report: boolean;
  has_data?: boolean;
  reason?: string;
  outcome?: string;
  resolution?: string;
  n_observations?: number;
  n_branches?: number;
  years?: [string, string];
  // headline — mean yearly IC with a Student-t CI over the series of yearly ICs
  mean_yearly_ic?: number | null;
  n_years?: number;
  ic_t_stat?: number | null;
  ic_ci?: [number | null, number | null];
  // secondary — pooled stacked Spearman (overstates precision; kept for transparency)
  spearman_pooled?: number | null;
  spearman_pooled_ci?: [number | null, number | null];
  spearman_pooled_note?: string;
  spearman_partial_growth?: number | null;
  spearman_partial_n?: number | null;
  by_year?: GateEByYear[];
  quintile_spread?: GateEQuintileSpread | null;
  // El desenlace primario ES el del encabezado desde el 2026-09-01: antes el encabezado
  // llevaba el de empleo, que este mismo reporte declara que el índice NO dice anticipar.
  outcome_primario?: string;
  headline_outcome?: string | null;
  /** Los DOS desenlaces contra los que se valida el eje, cada uno con lo suyo. El encabezado
   *  plano de arriba ES el primario; esto trae también el que no encabeza, porque un eje que
   *  corrió dos backtests y publica uno solo esconde un resultado. */
  outcomes?: Record<string, SectorGateEOutcome>;
  // CONTROL POR TAMAÑO. La intensidad de IED se divide por el tamaño del sector, y el tamaño
  // es una variable del IAI: sin este control, «el índice ordena al revés» y «el deflactor
  // produce el signo» son indistinguibles. No se re-juzga acá: el veredicto lo computa el
  // backend y esta pantalla lo lee.
  control_solo_tamano?: {
    mean_yearly_ic?: number | null;
    ic_ci?: [number | null, number | null];
    n_observations?: number;
  } | null;
  veredicto_contra_el_tamano?: string;
  empata_con_el_score?: boolean;
  el_tamano_alcanza_al_score?: boolean;
  invertido?: boolean;
  conclusive?: boolean;
  disclaimer?: string;
  generated_at?: string;
}

export async function getSectorValidation(): Promise<SectorGateEReport> {
  const { data } = await client.get("/sector-intel/validation");
  return data;
}

// ── Estructura sectorial agregada (importancia económica + contribución) ──
export interface StructureRow {
  slug: string;
  sector: string;
  weight: number | null;          // % del Valor Agregado
  growth: number | null;          // crecimiento real interanual %
  contribution: number | null;    // peso × crecimiento (pp)
  contribution_share: number | null;
}
export interface EconomicStructure {
  period: string | null;
  has_data: boolean;
  source: string;
  total_va_growth: number;
  coverage: number;
  contribution_coverage: number;
  concentration_hhi: number | null;
  n_sectors: number;
  sectors: StructureRow[];         // ranking por peso
  drivers: StructureRow[];         // motores (aporte +)
  drags: StructureRow[];           // lastres (aporte −)
  top_weight: StructureRow | null;
  top_driver: StructureRow | null;
  top_drag: StructureRow | null;
}

export async function getEconomicStructure(period?: string): Promise<EconomicStructure> {
  const { data } = await client.get("/sector-intel/structure", {
    params: period ? { period } : {},
  });
  return data;
}

/** AI narrative of the economic structure (institutional frame). Best-effort. */
export async function getStructureInsight(
  audience = "gobierno",
  deep = false,
): Promise<AiInsight | null> {
  const { data } = await client.get("/sector-intel/structure/insight", {
    params: { audience, ...(deep ? { deep: true } : {}) },
  });
  return (data.ai_insight as AiInsight | null) ?? null;
}

export async function runSectorGateE(): Promise<{ started: boolean; reason?: string }> {
  const { data } = await client.post("/operations/sector-gate-e/run", {});
  return data;
}

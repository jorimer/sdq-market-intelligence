import client from "@/shared/api/client";

export type SuggestionKind = "source" | "info_type" | "sector";
export type SuggestionStatus =
  | "proposed" | "evaluating" | "evaluated" | "approved"
  | "integrating" | "integrated" | "rejected" | "deferred";

export interface Suggestion {
  id: string;
  kind: SuggestionKind;
  title: string;
  description: string;
  origin: "manual" | "agent" | "catalog";
  proposed_by: string | null;
  target_axis: string | null;
  target_gate: string | null;
  status: SuggestionStatus;
  evaluation: Record<string, unknown> | null;
  integration_plan: Record<string, unknown> | null;
  decision_note: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SuggestionBoard {
  suggestions: Suggestion[];
  summary: Record<SuggestionStatus, number>;
}

export async function listSuggestions(params?: { status?: string; axis?: string }): Promise<SuggestionBoard> {
  const { data } = await client.get("/source-intel/suggestions", { params });
  return data;
}

export async function createSuggestion(input: {
  kind: SuggestionKind; title: string; description?: string;
  target_axis?: string | null; target_gate?: string | null;
}): Promise<Suggestion> {
  const { data } = await client.post("/source-intel/suggestions", input);
  return data;
}

export async function setSuggestionStatus(
  id: string, status: SuggestionStatus, decision_note?: string,
): Promise<Suggestion> {
  const { data } = await client.patch(`/source-intel/suggestions/${id}/status`, { status, decision_note });
  return data;
}

export async function evaluateSuggestion(id: string): Promise<Suggestion> {
  const { data } = await client.post(`/source-intel/suggestions/${id}/evaluate`);
  return data;
}

/** Dispara el agente de descubrimiento (operación async); las propuestas aparecen en
 * el tablero al terminar. Devuelve si arrancó. */
export async function runResearchAgent(): Promise<{ started: boolean; reason?: string }> {
  const { data } = await client.post("/operations/source-research-agent/run", {});
  return data;
}

/** Estado de la operación del agente: si corre + su último resultado (para refrescar el
 * tablero al terminar y avisar si topó el cap por corrida). */
export async function agentStatus(): Promise<{ running: boolean; lastResult: { created?: number; capped?: boolean } | null }> {
  const { data } = await client.get("/operations/status");
  const op = (data.operations || []).find(
    (o: { name: string }) => o.name === "source-research-agent");
  return { running: Boolean(op?.status?.is_running), lastResult: op?.status?.last_result ?? null };
}

/** Descubridor de catálogos: consulta APIs reales (CKAN datos.gob.do) y crea sugerencias
 * de datasets verificados. Operación async. */
export async function runCatalogDiscovery(): Promise<{ started: boolean; reason?: string }> {
  const { data } = await client.post("/operations/catalog-discovery/run", {});
  return data;
}

export async function discoveryStatus(): Promise<{ running: boolean; lastResult: { created?: number; capped?: boolean } | null }> {
  const { data } = await client.get("/operations/status");
  const op = (data.operations || []).find(
    (o: { name: string }) => o.name === "catalog-discovery");
  return { running: Boolean(op?.status?.is_running), lastResult: op?.status?.last_result ?? null };
}

export async function scaffoldSuggestion(id: string): Promise<Suggestion> {
  const { data } = await client.post(`/source-intel/suggestions/${id}/scaffold`);
  return data;
}

export async function deleteSuggestion(id: string): Promise<void> {
  await client.delete(`/source-intel/suggestions/${id}`);
}

/** Mantenimiento del tablero (rápido, sin IA): auto-difiere cubiertas + marca badges.
 * Síncrono — devuelve cuántas tocó. */
export async function runMaintenance(): Promise<{ deferred: number; flagged: number }> {
  const { data } = await client.post("/source-intel/maintenance");
  return data;
}

export interface IntegrationPlan {
  data_access: string;
  connector: string;
  crosswalk: string;
  target: string;
  steps: string[];
  risks: string[];
  effort: string;
  method: string;
}

export interface Evaluation {
  score: number;
  criteria: Record<string, { score: number; note: string }>;
  gate_closed: string | null;
  fit_rationale: string;
  recommendation: "approve" | "investigate" | "reject" | "defer";
  method: "ai" | "heuristic";
  already_covered?: boolean;
  coverage_note?: string;
}

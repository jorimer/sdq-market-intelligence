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
  origin: "manual" | "agent";
  proposed_by: string | null;
  target_axis: string | null;
  target_gate: string | null;
  status: SuggestionStatus;
  evaluation: Record<string, unknown> | null;
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

/** ¿La operación del agente sigue corriendo? (para refrescar el tablero al terminar). */
export async function agentRunning(): Promise<boolean> {
  const { data } = await client.get("/operations/status");
  const op = (data.operations || []).find(
    (o: { name: string }) => o.name === "source-research-agent");
  return Boolean(op?.status?.is_running);
}

export async function deleteSuggestion(id: string): Promise<void> {
  await client.delete(`/source-intel/suggestions/${id}`);
}

export interface Evaluation {
  score: number;
  criteria: Record<string, { score: number; note: string }>;
  gate_closed: string | null;
  fit_rationale: string;
  recommendation: "approve" | "investigate" | "reject" | "defer";
  method: "ai" | "heuristic";
}

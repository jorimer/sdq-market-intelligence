import client from "@/shared/api/client";

// Platform-wide Operation Console (cross-module): /api/v1/operations/*

export interface OperationStatus {
  is_running: boolean;
  phase: string;
  started_at: string | null;
  last_run: string | null;
  last_result: Record<string, unknown> | null;
  error: string | null;
  heartbeat: string | null;
}

export interface OperationSchedule {
  operation: string;
  enabled: boolean;
  interval_hours: number;
  params: Record<string, unknown>;
  next_run_at: string | null;
  last_run_at: string | null;
}

export interface OperationInfo {
  name: string;
  label: string;
  description: string;
  needs_params: string[];
  status: OperationStatus;
  schedule: OperationSchedule;
}

export interface OperationRunHistory {
  id: string;
  operation: string;
  origin: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  summary: Record<string, unknown> | null;
  error: string | null;
}

export interface OperationsStatus {
  operations: OperationInfo[];
  history: OperationRunHistory[];
}

export async function getOperationsStatus(): Promise<OperationsStatus> {
  const { data } = await client.get<OperationsStatus>("/operations/status");
  return data;
}

export async function triggerOperation(
  name: string,
  params?: Record<string, string>,
): Promise<{ started: boolean; reason?: string; run_id?: string }> {
  const { data } = await client.post(`/operations/${name}/run`, params ?? {});
  return data;
}

export async function setOperationSchedule(
  name: string,
  body: { enabled: boolean; interval_hours?: number; params?: Record<string, unknown> },
): Promise<OperationSchedule> {
  const { data } = await client.put<OperationSchedule>(`/operations/${name}/schedule`, body);
  return data;
}

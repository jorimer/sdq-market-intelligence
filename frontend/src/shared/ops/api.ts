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
  /** Bajo demanda: se ejecuta a mano, no admite agenda automática. */
  on_demand: boolean;
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

// ── Gasto del modelo ────────────────────────────────────────────────────
// El costo de cada llamada se calculaba y se tiraba: la única forma de saber en qué se
// iba el dinero era mirar la consola del proveedor antes y después de cada corrida.

export interface SpendRow {
  /** Clave técnica: la ruta o el nombre de la operación. Se conserva para depurar. */
  clave: string;
  /** Nombre del producto que consumió, resuelto por el backend. Puede faltar si la
   *  respuesta viene de una versión anterior; el panel cae a `clave`. */
  etiqueta?: string;
  costo_usd: number;
  llamadas: number;
  hits_de_cache: number;
  /** Llamadas que SÍ se pagaron. Un disparador con 900 llamadas y 890 HIT no es
   *  comparable con uno de 900 generaciones, y el conteo solo no lo distingue. */
  generaciones_reales: number;
}

export interface SpendSummary {
  desde: string;
  hasta: string;
  costo_total_usd: number;
  llamadas_totales: number;
  por_disparador: SpendRow[];
  por_modulo: SpendRow[];
  /** Separa PRODUCIR de VERIFICAR: el juez numérico corre sobre toda sección de toda
   *  generación, y sumado al mismo total su peso es invisible. */
  por_motivo: SpendRow[];
}

/** Gasto del modelo en un rango de FECHAS. `hasta` incluye el día completo.
 *  Va por fechas y no por ventana de N días porque la pregunta es si cuadra con la
 *  factura, y la facturación va por ciclo calendario. */
export async function getLlmSpend(desde?: string, hasta?: string): Promise<SpendSummary> {
  const params: Record<string, string> = {};
  if (desde) params.desde = desde;
  if (hasta) params.hasta = hasta;
  const { data } = await client.get<SpendSummary>("/operations/llm-spend", { params });
  return data;
}

// ── Frescura de la validación ───────────────────────────────────────────
// Un reporte de validación es un artefacto persistido: sigue sirviendo su cifra aunque el
// score que midió haya cambiado. Producción publicó así un Gini de 0,44 durante 19 días
// contra un deck que decía 0,16. Esto responde la pregunta que la consola no hacía: ¿la
// cifra de este eje sigue correspondiendo al insumo que la produjo?

export interface FrescuraEje {
  eje: string;
  operacion: string;
  tiene_reporte: boolean;
  generated_at?: string | null;
  /** false = vigente · true = obsoleto · null = INDETERMINADO (no es "está bien"). */
  stale: boolean | null;
  stale_reason: string | null;
  /** Insumos que la huella no cubre: el `false` no afirma sobre ellos. */
  stale_scope?: string[] | null;
  disparado_por?: string[];
  sin_cascada_motivo?: string | null;
}

export interface FrescuraValidacion {
  ejes: FrescuraEje[];
  obsoletos: string[];
  indeterminados: string[];
}

export async function getValidacionFrescura(): Promise<FrescuraValidacion> {
  const { data } = await client.get<FrescuraValidacion>("/operations/validacion");
  return data;
}

import { useCallback, useEffect, useRef, useState } from "react";
import { Wrench, RefreshCw, Play, Clock, History } from "lucide-react";
import { PageHead, Card, CardHead, StateBlock, Chip } from "@/shared/ui/primitives";
import {
  getOperationsStatus,
  triggerOperation,
  setOperationSchedule,
  OperationsStatus,
  OperationInfo,
} from "@/shared/ops/api";

const CADENCES: { label: string; hours: number }[] = [
  { label: "Diario", hours: 24 },
  { label: "Semanal", hours: 168 },
  { label: "Quincenal", hours: 336 },
  { label: "Mensual", hours: 720 },
  { label: "Trimestral", hours: 2160 },
  { label: "Anual", hours: 8760 },
];

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("es-DO", { dateStyle: "medium", timeStyle: "short" });
}

// Known result keys → human label (Spanish). Unknown keys fall back to a
// humanized version of the key, so a runner that adds a field never breaks.
const RESULT_LABELS: Record<string, string> = {
  // rescore / scoring
  periods_scored: "Períodos calificados",
  ratings_written: "Ratings escritos",
  ratings_total: "Ratings totales",
  scored_periods: "Períodos calculados",
  per_period: "Detalle por período",
  // prune / purge
  data_deleted: "Datos borrados",
  ratings_deleted: "Ratings borrados",
  actions_deleted: "Acciones borradas",
  purged: "Scores purgados",
  purged_periods: "Períodos purgados",
  synthetic_deleted: "Sintéticos borrados",
  orphan_ratings_deleted: "Ratings huérfanos borrados",
  orphan_actions_deleted: "Acciones huérfanas borradas",
  scores_deleted: "Scores borrados",
  flows_deleted: "Flujos borrados",
  // overview
  entities: "Entidades",
  records: "Registros",
  ratings: "Ratings",
  sib_records: "Registros SIB",
  period_start: "Inicio del período",
  period_end: "Fin del período",
  // backtest
  gini: "Gini",
  n_observations: "Observaciones",
  n_events: "Eventos",
  monotonic: "Monótona",
  // sync (WGI / ONE / DGA)
  synced: "Valores sincronizados",
  health_synced: "Salud (WDI) sincronizada",
  periods: "Períodos",
  period: "Período",
  countries: "Países",
  variables: "Variables",
  regions: "Regiones",
  regions_with_data: "Regiones con dato",
  themes: "Indicadores",
  latest: "Último",
  periods_ingested: "Trimestres ingeridos",
  ingested_ok: "Ingeridos OK",
  total: "Total",
  results: "Resultados",
  // common
  errors: "Errores",
  error: "Error",
  status: "Estado",
  message: "Mensaje",
};

function resultLabel(key: string): string {
  if (RESULT_LABELS[key]) return RESULT_LABELS[key];
  const spaced = key.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function fmtResultValue(key: string, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Sí" : "No";
  if (typeof value === "number") {
    if (Number.isInteger(value)) return value.toLocaleString("es-DO");
    return value.toLocaleString("es-DO", { maximumFractionDigits: 3 });
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return key === "errors" ? "ninguno" : "—";
    if (value.every((v) => v === null || ["string", "number", "boolean"].includes(typeof v))) {
      return value.map((v) => String(v)).join(", ");
    }
    return `${value.length} ítem${value.length === 1 ? "" : "s"}`;
  }
  if (typeof value === "object") {
    const n = Object.keys(value as Record<string, unknown>).length;
    return `${n} campo${n === 1 ? "" : "s"}`;
  }
  return String(value);
}

function ResultDetail({ result, when }: { result: Record<string, unknown>; when: string | null }) {
  const entries = Object.entries(result);
  return (
    <div className="mt-3">
      <div className="text-xs text-muted">
        Último resultado · <span className="mono text-body">{fmtDateTime(when)}</span>
      </div>
      <dl className="mt-1.5 divide-y divide-line/40">
        {entries.map(([k, v]) => (
          <div key={k} className="flex items-baseline justify-between gap-3 py-1">
            <dt className="text-xs text-muted min-w-0 flex-1 truncate" title={resultLabel(k)}>
              {resultLabel(k)}
            </dt>
            <dd
              className="text-xs mono text-body tabular-nums shrink-0 text-right max-w-[60%] truncate"
              title={fmtResultValue(k, v)}
            >
              {fmtResultValue(k, v)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function statusChip(op: OperationInfo) {
  const s = op.status;
  if (s.is_running) return <Chip tone="accent">En curso</Chip>;
  if (s.error || s.phase === "error") return <Chip tone="alert">Error</Chip>;
  if (s.phase === "completado") return <Chip tone="ok">Completado</Chip>;
  return <Chip tone="muted">Inactivo</Chip>;
}

function OperationCard({ op, onChanged }: { op: OperationInfo; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [period, setPeriod] = useState("");
  const [msg, setMsg] = useState<{ tone: "ok" | "alert"; text: string } | null>(null);
  const needsPeriod = op.needs_params.includes("period");

  const run = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const params = needsPeriod ? { period } : undefined;
      const res = await triggerOperation(op.name, params);
      if (!res.started) setMsg({ tone: "alert", text: res.reason ?? "No se pudo iniciar." });
      else setMsg({ tone: "ok", text: "Operación iniciada." });
      onChanged();
    } catch {
      setMsg({ tone: "alert", text: "Error al iniciar la operación." });
    } finally {
      setBusy(false);
    }
  };

  const toggleSchedule = async (enabled: boolean, hours?: number) => {
    try {
      await setOperationSchedule(op.name, {
        enabled,
        interval_hours: hours ?? op.schedule.interval_hours,
      });
      onChanged();
    } catch {
      setMsg({ tone: "alert", text: "No se pudo guardar el agendado." });
    }
  };

  const s = op.status;
  const result = s.last_result as Record<string, unknown> | null;

  return (
    <Card>
      <CardHead icon={Wrench} title={op.label} subtitle={op.description} right={statusChip(op)} />

      {s.is_running && (
        <div className="mt-3 flex items-center gap-2 text-sm text-accent">
          <RefreshCw className="w-4 h-4 animate-spin shrink-0" />
          <span className="truncate">{s.phase || "procesando…"}</span>
        </div>
      )}

      {!s.is_running && result && <ResultDetail result={result} when={s.last_run} />}
      {!s.is_running && s.error && <div className="mt-2 text-xs text-alert">{s.error}</div>}

      <div className="mt-4 flex flex-wrap items-end gap-2">
        {needsPeriod && (
          <div>
            <label className="block text-xs font-medium text-muted mb-1">Trimestre (YYYY-MM)</label>
            <input
              className="field !py-1.5 !px-2.5 text-sm w-32 mono"
              placeholder="2025-12"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
            />
          </div>
        )}
        <button
          onClick={run}
          disabled={busy || s.is_running || (needsPeriod && !period)}
          className="btn btn-primary !py-1.5"
        >
          <Play className="w-3.5 h-3.5" /> Ejecutar
        </button>
      </div>

      {msg && (
        <p className={`mt-2 text-xs ${msg.tone === "ok" ? "text-ok" : "text-alert"}`}>{msg.text}</p>
      )}

      {/* Schedule */}
      <div className="mt-4 pt-3 border-t border-line/60">
        <div className="flex items-center gap-2 mb-2">
          <Clock className="w-3.5 h-3.5 text-muted shrink-0" />
          <span className="text-xs font-medium text-ink">Agendar</span>
          <label className="ml-auto inline-flex items-center gap-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={op.schedule.enabled}
              onChange={(e) => toggleSchedule(e.target.checked)}
              className="accent-[var(--accent)]"
            />
            <span className="text-xs text-muted">{op.schedule.enabled ? "Activo" : "Inactivo"}</span>
          </label>
        </div>
        {op.schedule.enabled && (
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={op.schedule.interval_hours}
              onChange={(e) => toggleSchedule(true, Number(e.target.value))}
              className="field !py-1 !px-2 text-xs w-32"
            >
              {CADENCES.map((c) => (
                <option key={c.hours} value={c.hours}>{c.label}</option>
              ))}
              {!CADENCES.some((c) => c.hours === op.schedule.interval_hours) && (
                <option value={op.schedule.interval_hours}>
                  Cada {op.schedule.interval_hours}h
                </option>
              )}
            </select>
            <span className="text-xs text-muted">
              Próximo: <span className="mono text-body">{fmtDateTime(op.schedule.next_run_at)}</span>
            </span>
          </div>
        )}
      </div>
    </Card>
  );
}

interface Props {
  eyebrow: string;
  title: string;
  sub: string;
  /** Restrict the console to a subset of operations (by name). Omit for all. */
  filter?: (op: OperationInfo) => boolean;
  /** Empty-state copy when the filter matches no operation. */
  emptyMessage?: string;
  /** Source-specific "estado del dato" panel rendered above the operations
   * (coverage, provenance, freshness) — turns a per-source page into a data home. */
  overview?: React.ReactNode;
}

/** Platform-wide operation console: trigger, monitor and schedule data operations
 * from the UI (no terminal). Reused by the global console and the per-source
 * Datos pages, narrowed via *filter*. */
export function OperationsConsole({ eyebrow, title, sub, filter, emptyMessage, overview }: Props) {
  const [data, setData] = useState<OperationsStatus | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready" | "forbidden">("loading");
  const timer = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await getOperationsStatus());
      setStatus("ready");
    } catch (e: unknown) {
      const code = (e as { response?: { status?: number } })?.response?.status;
      setStatus(code === 403 ? "forbidden" : "error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const ops = (data?.operations ?? []).filter((o) => (filter ? filter(o) : true));
  const opNames = new Set(ops.map((o) => o.name));
  const history = (data?.history ?? []).filter((h) => (filter ? opNames.has(h.operation) : true));

  // Poll while any (visible) operation is running.
  const anyRunning = ops.some((o) => o.status.is_running);
  useEffect(() => {
    if (!anyRunning) return;
    timer.current = window.setInterval(load, 5000);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [anyRunning, load]);

  return (
    <div>
      <PageHead eyebrow={eyebrow} title={title} sub={sub} />

      {overview && <div className="mb-5">{overview}</div>}

      {status === "loading" && <StateBlock kind="loading" message="Cargando operaciones…" />}
      {status === "forbidden" && (
        <StateBlock kind="forbidden" message="Se requiere rol admin para la consola de operación." />
      )}
      {status === "error" && (
        <StateBlock kind="error" message="No se pudo cargar el estado de las operaciones." />
      )}

      {status === "ready" && (
        <div className="space-y-5">
          {ops.length === 0 ? (
            <StateBlock kind="empty" message={emptyMessage ?? "No hay operaciones para esta fuente."} />
          ) : (
            <div className="grid lg:grid-cols-3 gap-5">
              {ops.map((op) => (
                <OperationCard key={op.name} op={op} onChanged={load} />
              ))}
            </div>
          )}

          {ops.length > 0 && (
            <Card>
              <CardHead icon={History} title="Historial" subtitle="Últimas corridas" />
              {history.length === 0 ? (
                <StateBlock kind="empty" message="Aún no hay corridas registradas." />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-muted border-b border-line">
                        <th className="py-2 px-2">Operación</th>
                        <th className="py-2 px-2">Origen</th>
                        <th className="py-2 px-2">Estado</th>
                        <th className="py-2 px-2">Inicio</th>
                        <th className="py-2 px-2">Fin</th>
                      </tr>
                    </thead>
                    <tbody>
                      {history.map((h) => (
                        <tr key={h.id} className="border-b border-line/60 last:border-0">
                          <td className="py-2 px-2 text-ink">{h.operation}</td>
                          <td className="py-2 px-2 text-body">{h.origin}</td>
                          <td className="py-2 px-2">
                            <Chip
                              tone={
                                h.status === "completed" ? "ok" : h.status === "error" ? "alert" : "muted"
                              }
                            >
                              {h.status}
                            </Chip>
                          </td>
                          <td className="py-2 px-2 mono text-body">{fmtDateTime(h.started_at)}</td>
                          <td className="py-2 px-2 mono text-body">{fmtDateTime(h.finished_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

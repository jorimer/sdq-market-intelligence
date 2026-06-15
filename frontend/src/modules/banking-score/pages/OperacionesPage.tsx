import { useCallback, useEffect, useRef, useState } from "react";
import { Wrench, RefreshCw, Play, Clock, History } from "lucide-react";
import { PageHead, Card, CardHead, StateBlock, Chip } from "@/shared/ui/primitives";
import {
  getOperationsStatus,
  triggerOperation,
  setOperationSchedule,
  OperationsStatus,
  OperationInfo,
} from "../api";

const CADENCES: { label: string; hours: number }[] = [
  { label: "Diario", hours: 24 },
  { label: "Semanal", hours: 168 },
  { label: "Quincenal", hours: 336 },
  { label: "Mensual", hours: 720 },
];

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("es-DO", { dateStyle: "medium", timeStyle: "short" });
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
      <CardHead
        icon={Wrench}
        title={op.label}
        subtitle={op.description}
        right={statusChip(op)}
      />

      {s.is_running && (
        <div className="mt-3 flex items-center gap-2 text-sm text-accent">
          <RefreshCw className="w-4 h-4 animate-spin shrink-0" />
          <span className="truncate">{s.phase || "procesando…"}</span>
        </div>
      )}

      {!s.is_running && result && (
        <div className="mt-3 text-xs text-muted">
          Último resultado{" "}
          <span className="mono text-body">{fmtDateTime(s.last_run)}</span>:{" "}
          <span className="mono text-body tabular-nums">{JSON.stringify(result)}</span>
        </div>
      )}
      {!s.is_running && s.error && (
        <div className="mt-2 text-xs text-alert">{s.error}</div>
      )}

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

export function OperacionesPage() {
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

  // Poll while any operation is running.
  const anyRunning = data?.operations.some((o) => o.status.is_running) ?? false;
  useEffect(() => {
    if (!anyRunning) return;
    timer.current = window.setInterval(load, 5000);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [anyRunning, load]);

  return (
    <div>
      <PageHead
        eyebrow="Datos · operación"
        title="Consola de Operación"
        sub="Dispara, monitorea y agenda las operaciones de datos recurrentes — sin terminal."
      />

      {status === "loading" && <StateBlock kind="loading" message="Cargando operaciones…" />}
      {status === "forbidden" && (
        <StateBlock kind="forbidden" message="Se requiere rol admin para la consola de operación." />
      )}
      {status === "error" && (
        <StateBlock kind="error" message="No se pudo cargar el estado de las operaciones." />
      )}

      {status === "ready" && data && (
        <div className="space-y-5">
          <div className="grid lg:grid-cols-3 gap-5">
            {data.operations.map((op) => (
              <OperationCard key={op.name} op={op} onChanged={load} />
            ))}
          </div>

          <Card>
            <CardHead icon={History} title="Historial" subtitle="Últimas corridas (todas las fuentes)" />
            {data.history.length === 0 ? (
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
                    {data.history.map((h) => (
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
        </div>
      )}
    </div>
  );
}

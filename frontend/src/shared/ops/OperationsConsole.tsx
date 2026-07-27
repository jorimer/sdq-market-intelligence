import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Wrench, RefreshCw, Play, Clock, History } from "lucide-react";
import { PageHead, Card, CardHead, StateBlock, Chip } from "@/shared/ui/primitives";
import {
  getOperationsStatus,
  triggerOperation,
  setOperationSchedule,
  OperationsStatus,
  OperationInfo,
} from "@/shared/ops/api";

const LOCALES: Record<string, string> = { es: "es-DO", en: "en-US", fr: "fr-FR" };

const CADENCES: { key: string; hours: number }[] = [
  { key: "daily", hours: 24 },
  { key: "weekly", hours: 168 },
  { key: "biweekly", hours: 336 },
  { key: "monthly", hours: 720 },
  { key: "quarterly", hours: 2160 },
  { key: "annual", hours: 8760 },
];

function fmtDateTime(iso: string | null, locale: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
}

/** Known result key → localized label; unknown keys fall back to a humanized
 * version of the key, so a runner that adds a field never breaks. */
function resultLabel(t: TFunction, key: string): string {
  const spaced = key.replace(/_/g, " ");
  return t(`ops.results.${key}`, { defaultValue: spaced.charAt(0).toUpperCase() + spaced.slice(1) });
}

function fmtResultValue(t: TFunction, locale: string, key: string, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? t("ops.yes") : t("ops.no");
  if (typeof value === "number") {
    if (Number.isInteger(value)) return value.toLocaleString(locale);
    return value.toLocaleString(locale, { maximumFractionDigits: 3 });
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return key === "errors" ? t("ops.none") : "—";
    if (value.every((v) => v === null || ["string", "number", "boolean"].includes(typeof v))) {
      return value.map((v) => String(v)).join(", ");
    }
    return t("ops.items", { count: value.length });
  }
  if (typeof value === "object") {
    const n = Object.keys(value as Record<string, unknown>).length;
    return t("ops.fields", { count: n });
  }
  return String(value);
}

function ResultDetail({ result, when, t, locale }: { result: Record<string, unknown>; when: string | null; t: TFunction; locale: string }) {
  const entries = Object.entries(result);
  return (
    <div className="mt-3">
      <div className="text-xs text-muted">
        {t("ops.lastResult")} · <span className="mono text-body">{fmtDateTime(when, locale)}</span>
      </div>
      <dl className="mt-1.5 divide-y divide-line/40">
        {entries.map(([k, v]) => (
          <div key={k} className="flex items-baseline justify-between gap-3 py-1">
            <dt className="text-xs text-muted min-w-0 flex-1 truncate" title={resultLabel(t, k)}>
              {resultLabel(t, k)}
            </dt>
            <dd
              className="text-xs mono text-body tabular-nums shrink-0 text-right max-w-[60%] truncate"
              title={fmtResultValue(t, locale, k, v)}
            >
              {fmtResultValue(t, locale, k, v)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function statusChip(op: OperationInfo, t: TFunction) {
  const s = op.status;
  if (s.is_running) return <Chip tone="accent">{t("ops.running")}</Chip>;
  if (s.error || s.phase === "error") return <Chip tone="alert">{t("ops.errorChip")}</Chip>;
  if (s.phase === "completado") return <Chip tone="ok">{t("ops.completed")}</Chip>;
  return <Chip tone="muted">{t("ops.inactive")}</Chip>;
}

function OperationCard({ op, onChanged }: { op: OperationInfo; onChanged: () => void }) {
  const { t, i18n } = useTranslation();
  const locale = LOCALES[i18n.language] ?? "es-DO";
  const [busy, setBusy] = useState(false);
  const [period, setPeriod] = useState("");
  const [msg, setMsg] = useState<{ tone: "ok" | "alert"; text: string } | null>(null);
  // Estado OPTIMISTA del agendado: refleja el clic al instante (sin esperar el reload),
  // así el toggle nunca se ve "muerto". Se sincroniza desde props y revierte si el PUT falla.
  const [sched, setSched] = useState({ enabled: op.schedule.enabled, hours: op.schedule.interval_hours });
  useEffect(() => {
    setSched({ enabled: op.schedule.enabled, hours: op.schedule.interval_hours });
  }, [op.schedule.enabled, op.schedule.interval_hours]);
  const needsPeriod = op.needs_params.includes("period");
  // La descripción de las operaciones bajo demanda trae al final una nota "Correr cuando: …".
  // Se separa para mostrarla como un renglón propio y visible (no perdida al final del texto).
  const runWhenIdx = op.description.indexOf("Correr cuando:");
  const descMain = runWhenIdx >= 0 ? op.description.slice(0, runWhenIdx).trim() : op.description;
  const runWhen = runWhenIdx >= 0 ? op.description.slice(runWhenIdx).trim() : null;

  const run = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const params = needsPeriod ? { period } : undefined;
      const res = await triggerOperation(op.name, params);
      if (!res.started) setMsg({ tone: "alert", text: res.reason ?? t("ops.couldNotStart") });
      else setMsg({ tone: "ok", text: t("ops.startedOk") });
      onChanged();
    } catch {
      setMsg({ tone: "alert", text: t("ops.startError") });
    } finally {
      setBusy(false);
    }
  };

  const toggleSchedule = async (enabled: boolean, hours?: number) => {
    const intervalHours = hours ?? sched.hours;
    const prev = sched;
    setSched({ enabled, hours: intervalHours });  // optimista: feedback inmediato
    setMsg(null);
    try {
      await setOperationSchedule(op.name, { enabled, interval_hours: intervalHours });
      setMsg({ tone: "ok", text: t("ops.scheduleSaved") });
      onChanged();
    } catch {
      setSched(prev);  // revertir si el guardado falló
      setMsg({ tone: "alert", text: t("ops.scheduleError") });
    }
  };

  const s = op.status;
  const result = s.last_result as Record<string, unknown> | null;

  return (
    <Card>
      <CardHead icon={Wrench} title={op.label} subtitle={descMain} right={statusChip(op, t)} />

      {s.is_running && (
        <div className="mt-3 flex items-center gap-2 text-sm text-accent">
          <RefreshCw className="w-4 h-4 animate-spin shrink-0" />
          <span className="truncate">{s.phase || t("ops.processing")}</span>
        </div>
      )}

      {!s.is_running && result && <ResultDetail result={result} when={s.last_run} t={t} locale={locale} />}
      {!s.is_running && s.error && <div className="mt-2 text-xs text-alert">{s.error}</div>}

      <div className="mt-4 flex flex-wrap items-end gap-2">
        {needsPeriod && (
          <div>
            <label className="block text-xs font-medium text-muted mb-1">{t("ops.quarterLabel")}</label>
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
          <Play className="w-3.5 h-3.5" /> {t("ops.run")}
        </button>
      </div>

      {msg && (
        <p className={`mt-2 text-xs ${msg.tone === "ok" ? "text-ok" : "text-alert"}`}>{msg.text}</p>
      )}

      {/* Schedule */}
      <div className="mt-4 pt-3 border-t border-line/60">
        <div className="flex items-center gap-2 mb-2">
          <Clock className="w-3.5 h-3.5 text-muted shrink-0" />
          <span className="text-xs font-medium text-ink">{t("ops.schedule")}</span>
          {op.on_demand ? (
            <span className="ml-auto text-xs text-muted">{t("ops.onDemandOnly")}</span>
          ) : (
            <label className="ml-auto inline-flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={sched.enabled}
                onChange={(e) => toggleSchedule(e.target.checked)}
                className="accent-[var(--accent)]"
              />
              <span className="text-xs text-muted">{sched.enabled ? t("ops.schedActive") : t("ops.schedInactive")}</span>
            </label>
          )}
        </div>
        {op.on_demand && runWhen && (
          <p className="text-xs text-body/85 bg-accent-soft/50 border-l-2 border-accent rounded-r px-2 py-1">
            {runWhen}
          </p>
        )}
        {!op.on_demand && sched.enabled && (
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={sched.hours}
              onChange={(e) => toggleSchedule(true, Number(e.target.value))}
              className="field !py-1 !px-2 text-xs w-32"
            >
              {CADENCES.map((c) => (
                <option key={c.hours} value={c.hours}>{t(`ops.cadence.${c.key}`)}</option>
              ))}
              {!CADENCES.some((c) => c.hours === sched.hours) && (
                <option value={sched.hours}>
                  {t("ops.everyHours", { hours: sched.hours })}
                </option>
              )}
            </select>
            <span className="text-xs text-muted">
              {t("ops.next")} <span className="mono text-body">{fmtDateTime(op.schedule.next_run_at, locale)}</span>
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
  const { t, i18n } = useTranslation();
  const locale = LOCALES[i18n.language] ?? "es-DO";
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

      {status === "loading" && <StateBlock kind="loading" message={t("ops.loading")} />}
      {status === "forbidden" && (
        <StateBlock kind="forbidden" message={t("ops.forbidden")} />
      )}
      {status === "error" && (
        <StateBlock kind="error" message={t("ops.loadError")} />
      )}

      {status === "ready" && (
        <div className="space-y-5">
          {ops.length === 0 ? (
            <StateBlock kind="empty" message={emptyMessage ?? t("ops.emptyDefault")} />
          ) : (
            <div className="grid lg:grid-cols-3 gap-5">
              {ops.map((op) => (
                <OperationCard key={op.name} op={op} onChanged={load} />
              ))}
            </div>
          )}

          {ops.length > 0 && (
            <Card>
              <CardHead icon={History} title={t("ops.history")} subtitle={t("ops.historySub")} />
              {history.length === 0 ? (
                <StateBlock kind="empty" message={t("ops.historyEmpty")} />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-muted border-b border-line">
                        <th className="py-2 px-2">{t("ops.colOperation")}</th>
                        <th className="py-2 px-2">{t("ops.colOrigin")}</th>
                        <th className="py-2 px-2">{t("ops.colStatus")}</th>
                        <th className="py-2 px-2">{t("ops.colStart")}</th>
                        <th className="py-2 px-2">{t("ops.colEnd")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {history.map((h) => {
                        // Incidentes agrupados (p.ej. narrative-degraded): el summary trae un
                        // `count` acumulado en la ventana. Se muestra como un contador discreto
                        // junto al nombre; el detalle va en el title (hover). Solo afecta filas
                        // que lo traen — el resto de operaciones queda igual.
                        const count =
                          typeof h.summary?.count === "number" ? h.summary.count : null;
                        return (
                        <tr key={h.id} className="border-b border-line/60 last:border-0">
                          <td className="py-2 px-2 text-ink">
                            {h.operation}
                            {count && count > 1 ? (
                              <span
                                className="ml-2 text-xs text-muted tabular-nums"
                                title={t("ops.groupedCount", { count })}
                              >
                                ×{count}
                              </span>
                            ) : null}
                          </td>
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
                          <td className="py-2 px-2 mono text-body">{fmtDateTime(h.started_at, locale)}</td>
                          <td className="py-2 px-2 mono text-body">{fmtDateTime(h.finished_at, locale)}</td>
                        </tr>
                        );
                      })}
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

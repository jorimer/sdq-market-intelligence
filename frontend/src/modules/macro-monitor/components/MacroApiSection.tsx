import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Database, History, ListTree } from "lucide-react";
import { Card, CardHead, StatTile, Chip, StateBlock, Skeleton } from "@/shared/ui/primitives";
import { SeriesMaintenanceSection } from "@/modules/platform/components/SeriesMaintenanceSection";
import {
  getIndicators,
  getSignals,
  refresh as refreshLive,
  backfillHistorico,
  MacroIndicator,
  MacroSignal,
} from "../api";

type Status = "loading" | "error" | "ready";

const TREND_TONE: Record<string, "ok" | "alert" | "muted" | "warn"> = {
  acelerando: "ok",
  desacelerando: "warn",
  estable: "muted",
  insuficiente: "muted",
};

function fmt(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return Math.abs(v) >= 1000 ? v.toLocaleString("es-DO", { maximumFractionDigits: 1 }) : String(v);
}

/** Operational console for the BCRD live API connector: live ingest, historical
 * backfill (IPC + FX), the series inventory, and orphan-series maintenance. */
export function MacroApiSection() {
  const [items, setItems] = useState<MacroIndicator[]>([]);
  const [signals, setSignals] = useState<MacroSignal[]>([]);
  const [status, setStatus] = useState<Status>("loading");
  const [busy, setBusy] = useState<"" | "live" | "backfill">("");
  const [msg, setMsg] = useState<{ tone: "ok" | "alert"; text: string } | null>(null);
  const [yearFrom, setYearFrom] = useState(1984);
  const [yearTo, setYearTo] = useState(new Date().getFullYear());

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const [ind, sig] = await Promise.all([getIndicators(), getSignals()]);
      setItems(ind);
      setSignals(sig);
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const runLive = async () => {
    setBusy("live");
    setMsg(null);
    try {
      await refreshLive();
      setMsg({ tone: "ok", text: "Ingesta live completada y snapshot recomputado." });
      await load();
    } catch (e: unknown) {
      const s = (e as { response?: { status?: number } })?.response?.status;
      setMsg({
        tone: "alert",
        text: s === 403 ? "Requiere rol de administrador." : "No se pudo ingerir. Reintenta.",
      });
    } finally {
      setBusy("");
    }
  };

  const runBackfill = async () => {
    setBusy("backfill");
    setMsg(null);
    try {
      const r = await backfillHistorico(yearFrom, yearTo);
      setMsg({
        tone: "ok",
        text: `Backfill: ${r.touched.toLocaleString("es-DO")} observaciones (${r.period_min ?? "—"} → ${r.period_max ?? "—"}).`,
      });
      await load();
    } catch (e: unknown) {
      const s = (e as { response?: { status?: number } })?.response?.status;
      setMsg({
        tone: "alert",
        text:
          s === 403
            ? "Requiere rol de administrador."
            : s === 400
              ? "Falta el token del BCRD o la fuente está deshabilitada (Configuración → BCRD)."
              : "No se pudo correr el backfill. Reintenta.",
      });
    } finally {
      setBusy("");
    }
  };

  if (status === "error") {
    return (
      <StateBlock
        kind="error"
        message="No se pudieron cargar las series macro. Reintenta en unos segundos."
        action={
          <button className="btn btn-ghost" onClick={load}>
            Reintentar
          </button>
        }
      />
    );
  }

  const totalObs = items.reduce((a, i) => a + (i.n_obs ?? 0), 0);
  const withHistory = items.filter((i) => (i.n_obs ?? 0) >= 6).length;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatTile label="Series" value={items.length} />
        <StatTile label="Observaciones" value={totalObs} />
        <StatTile label="Con histórico" value={withHistory} />
        <StatTile label="Señales activas" value={signals.length} />
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        <Card>
          <CardHead
            icon={Database}
            title="Ingesta live (API BCRD)"
            subtitle="Trae el último valor de las series del conector y recomputa el snapshot"
          />
          <p className="text-sm text-muted mb-4">
            La mayoría de las series del API son <span className="text-ink">snapshot</span> (solo el
            último valor); para profundidad histórica usa el backfill o el motor de Excel.
          </p>
          <button onClick={runLive} disabled={busy !== ""} className="btn btn-primary">
            <RefreshCw className={`w-4 h-4 ${busy === "live" ? "animate-spin" : ""}`} />
            {busy === "live" ? "Ingiriendo…" : "Refrescar series live"}
          </button>
        </Card>

        <Card>
          <CardHead
            icon={History}
            title="Backfill histórico (IPC + tipo de cambio)"
            subtitle="Las dos únicas series con profundidad vía API (mensual)"
          />
          <div className="flex items-end gap-3 mb-4">
            <label className="block">
              <span className="block text-xs font-medium text-muted mb-1">Desde</span>
              <input
                type="number"
                className="field mono w-24"
                value={yearFrom}
                min={1984}
                max={yearTo}
                onChange={(e) => setYearFrom(Number(e.target.value))}
              />
            </label>
            <label className="block">
              <span className="block text-xs font-medium text-muted mb-1">Hasta</span>
              <input
                type="number"
                className="field mono w-24"
                value={yearTo}
                min={yearFrom}
                onChange={(e) => setYearTo(Number(e.target.value))}
              />
            </label>
          </div>
          <button onClick={runBackfill} disabled={busy !== ""} className="btn btn-soft">
            <History className={`w-4 h-4 ${busy === "backfill" ? "animate-spin" : ""}`} />
            {busy === "backfill" ? "Corriendo…" : "Correr backfill"}
          </button>
        </Card>
      </div>

      {msg && (
        <div
          className={`text-sm p-3 rounded-[10px] ${msg.tone === "alert" ? "bg-alert-soft text-alert" : "bg-ok-soft text-ok"}`}
        >
          {msg.text}
        </div>
      )}

      <Card>
        <CardHead icon={ListTree} title="Inventario de series" subtitle={`${items.length} series ingeridas`} />
        {status === "loading" ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-8" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <StateBlock kind="empty" message="Aún no hay series ingeridas. Refresca las series live para empezar." />
        ) : (
          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-line">
                  <th className="py-2 px-1 font-medium">Serie</th>
                  <th className="py-2 px-1 font-medium">Unidad</th>
                  <th className="py-2 px-1 font-medium text-right">Obs.</th>
                  <th className="py-2 px-1 font-medium">Último período</th>
                  <th className="py-2 px-1 font-medium text-right">Último valor</th>
                  <th className="py-2 px-1 font-medium">Tendencia</th>
                </tr>
              </thead>
              <tbody>
                {items.map((i) => (
                  <tr key={i.series_code} className="border-b border-line/60 last:border-0">
                    <td className="py-2 px-1 min-w-0">
                      <div className="text-ink truncate max-w-[22rem]">{i.label || i.series_code}</div>
                      <div className="mono text-[11px] text-faint truncate max-w-[22rem]">{i.series_code}</div>
                    </td>
                    <td className="py-2 px-1 text-body">{i.unit ?? "—"}</td>
                    <td className="py-2 px-1 text-right mono tabular-nums">{i.n_obs}</td>
                    <td className="py-2 px-1 mono text-body">{i.latest_period ?? "—"}</td>
                    <td className="py-2 px-1 text-right mono tabular-nums text-ink">{fmt(i.latest_value)}</td>
                    <td className="py-2 px-1">
                      <Chip tone={TREND_TONE[i.trend] ?? "muted"}>{i.trend}</Chip>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <SeriesMaintenanceSection />
    </div>
  );
}

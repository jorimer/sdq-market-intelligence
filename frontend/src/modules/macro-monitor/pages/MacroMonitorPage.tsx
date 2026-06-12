import { useEffect, useState, useCallback } from "react";
import { AlertTriangle, TrendingUp, TrendingDown, Minus, Activity } from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  StatTile,
  Chip,
  Delta,
  StateBlock,
  LoadingGrid,
} from "@/shared/ui/primitives";
import { ScenarioFan } from "@/shared/charts/ScenarioFan";
import { fmtNum } from "@/shared/lib/format";
import { Tone } from "@/shared/lib/bands";
import {
  getIndicators,
  getSignals,
  getSeries,
  refresh,
  MacroIndicator,
  MacroSignal,
  SeriesDetail,
} from "../api";

type Status = "loading" | "error" | "empty" | "ready";

const TREND_META: Record<string, { tone: Tone; label: string; icon: typeof TrendingUp }> = {
  acelerando: { tone: "ok", label: "Acelerando", icon: TrendingUp },
  desacelerando: { tone: "alert", label: "Desacelerando", icon: TrendingDown },
  estable: { tone: "muted", label: "Estable", icon: Minus },
  insuficiente: { tone: "muted", label: "Insuficiente", icon: Minus },
};

const SEVERITY_TONE: Record<string, Tone> = {
  alto: "alert",
  elevado: "warn",
  bajo: "ok",
};

export function MacroMonitorPage() {
  const [status, setStatus] = useState<Status>("loading");
  const [indicators, setIndicators] = useState<MacroIndicator[]>([]);
  const [signals, setSignals] = useState<MacroSignal[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [seriesCode, setSeriesCode] = useState("");
  const [series, setSeries] = useState<SeriesDetail | null>(null);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const [ind, sig] = await Promise.all([getIndicators(), getSignals()]);
      setIndicators(ind);
      setSignals(sig);
      if (ind.length && !seriesCode) {
        // Default the trajectory chart to the series with the most history, so it
        // plots a real curve instead of "datos insuficientes" on a snapshot series.
        const richest = ind.reduce((a, b) => ((b.n_obs ?? 0) > (a.n_obs ?? 0) ? b : a));
        setSeriesCode(richest.series_code);
      }
      setStatus(ind.length === 0 ? "empty" : "ready");
    } catch {
      setStatus("error");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (seriesCode) getSeries(seriesCode).then(setSeries).catch(() => setSeries(null));
  }, [seriesCode]);

  const doRefresh = async () => {
    setRefreshing(true);
    try {
      await refresh();
      await load();
    } catch {
      setStatus("error");
    } finally {
      setRefreshing(false);
    }
  };

  const head = (
    <PageHead
      eyebrow="BCRD · Monitor de coyuntura"
      title="Macroeconómico"
      sub="Momentum y puntos de inflexión sobre datos del BCRD. Detecta fragilidad temprana y traduce el entorno en señales para los demás ejes."
      right={
        <button onClick={doRefresh} disabled={refreshing} className="btn btn-soft">
          {refreshing ? "Actualizando…" : "Actualizar"}
        </button>
      }
    />
  );

  if (status === "loading") {
    return (
      <div>
        {head}
        <LoadingGrid />
      </div>
    );
  }

  if (status === "error") {
    return (
      <div>
        {head}
        <StateBlock
          kind="error"
          message="No se pudieron cargar los indicadores macro. Reintenta en unos segundos."
          action={
            <button onClick={load} className="btn btn-ghost">
              Reintentar
            </button>
          }
        />
      </div>
    );
  }

  if (status === "empty") {
    return (
      <div>
        {head}
        <StateBlock
          kind="empty"
          message="Aún no hay un snapshot macro. Genera el primero ingiriendo las series del BCRD."
          action={
            <button onClick={doRefresh} disabled={refreshing} className="btn btn-primary">
              {refreshing ? "Generando…" : "Generar snapshot"}
            </button>
          }
        />
      </div>
    );
  }

  const accelerating = indicators.filter((i) => i.trend === "acelerando").length;

  return (
    <div>
      {head}

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <StatTile label="Series monitoreadas" value={indicators.length} />
        <StatTile label="Señales activas" value={signals.length} />
        <StatTile label="En aceleración" value={accelerating} />
        <StatTile
          label="Sin señales = "
          value={signals.length === 0 ? "estable" : "vigilar"}
        />
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        {/* Indicators table */}
        <div className="lg:col-span-2">
          <Card>
            <CardHead
              icon={TrendingUp}
              title="Indicadores con momentum"
              subtitle="Cambio, aceleración y tendencia por serie"
            />
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted border-b border-line">
                    <th className="py-2 px-1 font-medium">Serie</th>
                    <th className="py-2 px-1 font-medium text-right">Último</th>
                    <th className="py-2 px-1 font-medium text-right">Δ</th>
                    <th className="py-2 px-1 font-medium text-right">Aceleración</th>
                    <th className="py-2 px-1 font-medium">Tendencia</th>
                  </tr>
                </thead>
                <tbody>
                  {indicators.map((i) => {
                    const tm = TREND_META[i.trend] ?? TREND_META.estable;
                    return (
                      <tr key={i.series_code} className="border-b border-line/60 last:border-0">
                        <td className="py-2.5 px-1 text-ink" title={i.series_code}>
                          {i.label ?? i.series_code}
                          {i.unit ? (
                            <span className="text-muted text-xs ml-1">({i.unit})</span>
                          ) : null}
                        </td>
                        <td className="py-2.5 px-1 text-right mono text-ink">
                          {fmtNum(i.latest_value, 1)}
                        </td>
                        <td className="py-2.5 px-1 text-right">
                          <Delta value={i.change} />
                        </td>
                        <td className="py-2.5 px-1 text-right mono text-body">
                          {fmtNum(i.acceleration, 2)}
                        </td>
                        <td className="py-2.5 px-1">
                          <Chip tone={tm.tone}>{tm.label}</Chip>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        </div>

        {/* Signals */}
        <div>
          <Card>
            <CardHead
              icon={AlertTriangle}
              title="Señales de alerta"
              subtitle="Reinhart-Rogoff · Calvo"
            />
            {signals.length === 0 ? (
              <p className="text-sm text-muted py-4 text-center">Sin señales activas.</p>
            ) : (
              <ul className="space-y-2.5">
                {signals.map((s, idx) => (
                  <li
                    key={idx}
                    className="flex items-start gap-3 rounded-[10px] bg-surface2 p-3"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-semibold text-ink truncate">
                        {s.signal === "debt_overhang"
                          ? "Sobreendeudamiento"
                          : s.signal === "sudden_stop"
                            ? "Freno súbito"
                            : s.signal}
                      </div>
                      <div className="text-xs text-muted mt-0.5">
                        {s.framework}
                        {s.series ? ` · ${s.series}` : ""}
                      </div>
                    </div>
                    <Chip tone={SEVERITY_TONE[s.severity] ?? "muted"}>{s.severity}</Chip>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

      {/* Trajectory + projection */}
      <Card className="mt-5">
        <CardHead
          icon={Activity}
          title="Trayectoria & proyección"
          subtitle="Histórico + proyección con banda de incertidumbre"
          right={
            <select
              value={seriesCode}
              onChange={(e) => setSeriesCode(e.target.value)}
              className="field !w-auto text-xs"
              title="Serie"
            >
              {indicators.map((i) => (
                <option key={i.series_code} value={i.series_code}>
                  {i.label ?? i.series_code}
                  {i.unit ? ` (${i.unit})` : ""}
                </option>
              ))}
            </select>
          }
        />
        {series ? (
          <ScenarioFan
            points={series.observations}
            projection={
              series.momentum?.latest_value != null && series.momentum.change != null && series.momentum.uncertainty_band
                ? {
                    value: series.momentum.latest_value + series.momentum.change,
                    band: series.momentum.uncertainty_band,
                  }
                : null
            }
          />
        ) : (
          <p className="text-sm text-muted py-6 text-center">Selecciona una serie.</p>
        )}
      </Card>
    </div>
  );
}

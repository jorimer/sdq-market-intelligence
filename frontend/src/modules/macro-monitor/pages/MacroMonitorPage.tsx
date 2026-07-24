import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, TrendingUp, TrendingDown, Minus, Activity, Sparkles } from "lucide-react";
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
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import { AudienceTabs } from "@/shared/ui/AudienceTabs";
import { useAudiencePref } from "@/shared/lib/useAudiencePref";
import { FiscalSection } from "../components/FiscalSection";
import { ScenarioFan } from "@/shared/charts/ScenarioFan";
import { fmtNum } from "@/shared/lib/format";
import { Tone } from "@/shared/lib/bands";
import {
  getIndicators,
  getSignals,
  getSeries,
  getSeriesInsight,
  getMacroSnapshotInsight,
  MACRO_AUDIENCES,
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
  const { t } = useTranslation();
  const [status, setStatus] = useState<Status>("loading");
  const [audience, setAudience] = useAudiencePref("sdq.macro.audience", MACRO_AUDIENCES);
  const [indicators, setIndicators] = useState<MacroIndicator[]>([]);
  const [signals, setSignals] = useState<MacroSignal[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [showAll, setShowAll] = useState(false);
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
      eyebrow={t("macro.eyebrow")}
      title={t("macro.title")}
      sub={t("macro.sub")}
      right={
        <button onClick={doRefresh} disabled={refreshing} className="btn btn-soft">
          {refreshing ? t("macro.refreshing") : t("macro.refresh")}
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
          message={t("macro.errorLoad")}
          action={
            <button onClick={load} className="btn btn-ghost">
              {t("common_retry")}
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
          message={t("macro.emptyMsg")}
          action={
            <button onClick={doRefresh} disabled={refreshing} className="btn btn-primary">
              {refreshing ? t("macro.generating") : t("macro.generateSnapshot")}
            </button>
          }
        />
      </div>
    );
  }

  const accelerating = indicators.filter((i) => i.trend === "acelerando").length;
  const latestPeriod =
    indicators.map((i) => i.latest_period).filter(Boolean).sort().slice(-1)[0] ?? "none";

  // Curate the table to the material movers (by |aceleración|); the full 292
  // series live behind a drill-down so the page leads with the narrative, not a wall.
  const HEADLINE_N = 25;
  const movers = [...indicators]
    .filter((i) => i.acceleration != null && i.trend !== "insuficiente")
    .sort((a, b) => Math.abs(b.acceleration as number) - Math.abs(a.acceleration as number));
  const tableRows = showAll ? indicators : movers.slice(0, HEADLINE_N);

  return (
    <div>
      {head}

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <StatTile label={t("macro.kpiSeries")} value={indicators.length} />
        <StatTile label={t("macro.kpiSignals")} value={signals.length} />
        <StatTile label={t("macro.kpiAccelerating")} value={accelerating} />
        <StatTile
          label={t("macro.kpiNoSignals")}
          value={signals.length === 0 ? t("macro.stable") : t("macro.watch")}
        />
      </div>

      {/* Coyuntura (IA) */}
      <div className="mb-5">
        <AiInsightCard
          title={t("macro.coyunturaTitle")}
          subtitle={t("macro.coyunturaSubtitle")}
          icon={Sparkles}
          depsKey={`coyuntura:${latestPeriod}:${indicators.length}:${audience}`}
          fetcher={() => getMacroSnapshotInsight(undefined, audience)}
          deepFetcher={(deep) => getMacroSnapshotInsight(undefined, audience, deep)}
          actions={
            <AudienceTabs
              value={audience}
              onChange={setAudience}
              options={MACRO_AUDIENCES}
              labelPrefix="macro.audience"
              ariaLabelKey="macro.audienceLabel"
            />
          }
        />
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        {/* Indicators table */}
        <div className="lg:col-span-2">
          <Card>
            <CardHead
              icon={TrendingUp}
              title={showAll ? t("macro.tableTitleAll") : t("macro.tableTitleMovers")}
              subtitle={
                showAll
                  ? t("macro.tableSubAll", { n: indicators.length })
                  : t("macro.tableSubMovers", { n: Math.min(HEADLINE_N, movers.length) })
              }
              right={
                <button
                  onClick={() => setShowAll((v) => !v)}
                  className="btn btn-ghost !py-1 !px-2.5 text-xs"
                >
                  {showAll ? t("macro.viewActive") : t("macro.viewAll", { n: indicators.length })}
                </button>
              }
            />
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted border-b border-line">
                    <th className="py-2 px-1 font-medium">{t("macro.colSeries")}</th>
                    <th className="py-2 px-1 font-medium text-right">{t("macro.colLatest")}</th>
                    <th className="py-2 px-1 font-medium text-right">{t("macro.colDelta")}</th>
                    <th className="py-2 px-1 font-medium text-right">{t("macro.colAccel")}</th>
                    <th className="py-2 px-1 font-medium">{t("macro.colTrend")}</th>
                  </tr>
                </thead>
                <tbody>
                  {tableRows.length === 0 && (
                    <tr>
                      <td colSpan={5} className="py-4 text-center text-sm text-muted">
                        {t("macro.emptyMomentum")}{" "}
                        <button onClick={() => setShowAll(true)} className="text-accent underline">
                          {t("macro.viewAll", { n: indicators.length })}
                        </button>
                      </td>
                    </tr>
                  )}
                  {tableRows.map((i) => {
                    const tm = TREND_META[i.trend] ?? TREND_META.estable;
                    const trendLabel = t(`macro.trend.${i.trend}`, tm.label);
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
                          <Chip tone={tm.tone}>{trendLabel}</Chip>
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
              title={t("macro.signalsTitle")}
              subtitle={t("macro.signalsSubtitle")}
            />
            {signals.length === 0 ? (
              <p className="text-sm text-muted py-4 text-center">{t("macro.noSignals")}</p>
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
                          ? t("macro.signalDebt")
                          : s.signal === "sudden_stop"
                            ? t("macro.signalSuddenStop")
                            : s.signal}
                      </div>
                      <div className="text-xs text-muted mt-0.5">
                        {s.framework}
                        {(s.label ?? s.series) ? ` · ${s.label ?? s.series}` : ""}
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
          title={t("macro.trajectoryTitle")}
          subtitle={t("macro.trajectorySubtitle")}
          right={
            <select
              value={seriesCode}
              onChange={(e) => setSeriesCode(e.target.value)}
              className="field !w-auto text-xs"
              title={t("macro.seriesSelect")}
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
          <p className="text-sm text-muted py-6 text-center">{t("macro.selectSeries")}</p>
        )}
      </Card>

      {/* Series analysis (IA) */}
      {seriesCode && (
        <div className="mt-5">
          <AiInsightCard
            title={t("macro.seriesInsightTitle")}
            subtitle={series?.series_code ?? seriesCode}
            icon={Activity}
            depsKey={`serie:${seriesCode}:${audience}`}
            fetcher={() => getSeriesInsight(seriesCode, audience)}
            deepFetcher={(deep) => getSeriesInsight(seriesCode, audience, deep)}
          />
        </div>
      )}

      {/* Pulso fiscal (Eje 2) */}
      <div className="mt-8">
        <h2 className="font-display text-lg font-bold text-ink mb-1">{t("macro.fiscalPulseTitle")}</h2>
        <p className="text-sm text-muted mb-4">
          {t("macro.fiscalPulseSub")}
        </p>
        <FiscalSection />
      </div>
    </div>
  );
}

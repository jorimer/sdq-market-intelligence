import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Landmark, RefreshCw } from "lucide-react";
import { Card, CardHead, StatTile, StateBlock } from "@/shared/ui/primitives";
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import { AudienceTabs } from "@/shared/ui/AudienceTabs";
import { useAudiencePref } from "@/shared/lib/useAudiencePref";
import { fmtNum } from "@/shared/lib/format";
import { FiscalPulse, getFiscalInsight, getFiscalPulse, MACRO_AUDIENCES } from "../api";

function fmtMM(v: number | null | undefined, t: TFunction): string {
  return v == null ? "—" : t("macro.fiscalMM", { v: fmtNum(v, 0) });
}

/** Merge ingresos + gastos timelines into one series for the last `months` points. */
function mergeTimeline(p: FiscalPulse, months = 36) {
  const ing = new Map((p.eo?.ingresos ?? []).map((d) => [d.period, d.value]));
  const gas = new Map((p.eo?.gastos ?? []).map((d) => [d.period, d.value]));
  const periods = Array.from(new Set([...ing.keys(), ...gas.keys()])).sort();
  return periods
    .slice(-months)
    .map((period) => ({ period, ingresos: ing.get(period) ?? null, gastos: gas.get(period) ?? null }));
}

export function FiscalSection() {
  const { t } = useTranslation();
  const [audience, setAudience] = useAudiencePref("sdq.macro.audience", MACRO_AUDIENCES);
  const [pulse, setPulse] = useState<FiscalPulse | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");

  const load = useCallback(async () => {
    try {
      setPulse(await getFiscalPulse());
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (status === "loading") return <StateBlock kind="loading" message={t("macro.fiscalLoading")} />;
  if (status === "error") return <StateBlock kind="error" message={t("macro.fiscalError")} />;
  if (!pulse?.has_data) {
    return (
      <StateBlock kind="empty" message={t("macro.fiscalEmpty")} />
    );
  }

  const data = mergeTimeline(pulse);
  const lat = pulse.eo_latest ?? { ingresos: null, gastos: null, balance_global: null };
  const deficit = lat.balance_global ?? null;
  const groups = pulse.recaudacion?.groups ?? [];
  const maxRec = Math.max(1, ...groups.map((g) => g.value));

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatTile label={t("macro.fiscalStatIngresos", { period: pulse.latest_period ?? "" })} value={fmtMM(lat.ingresos, t)} />
        <StatTile label={t("macro.fiscalStatGastos")} value={fmtMM(lat.gastos, t)} />
        <StatTile label={t("macro.fiscalStatDeficit")} value={fmtMM(deficit, t)} />
        <StatTile
          label={t("macro.fiscalStatCoverage")}
          value={pulse.period_range ? `${pulse.period_range[0]} – ${pulse.period_range[1]}` : "—"}
        />
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        <Card className="lg:col-span-2">
          <CardHead
            icon={Landmark}
            title={t("macro.fiscalChartTitle")}
            subtitle={t("macro.fiscalChartSubtitle", { unit: pulse.eo_unit ?? "RD$ MM" })}
          />
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
              <XAxis dataKey="period" tick={{ fontSize: 10, fill: "var(--muted)" }} stroke="var(--border-strong)" minTickGap={28} />
              <YAxis tick={{ fontSize: 10, fill: "var(--muted)" }} stroke="var(--border-strong)" width={56}
                tickFormatter={(v: number) => fmtNum(v / 1000, 0) + "k"} />
              <Tooltip
                formatter={(v: number, name: string) => [fmtMM(v, t), name === "ingresos" ? t("macro.fiscalIngresos") : t("macro.fiscalGastos")]}
                contentStyle={{ borderRadius: 8, fontSize: 12, background: "var(--surface)", border: "1px solid var(--border)", color: "var(--ink)" }}
              />
              <Line type="monotone" dataKey="ingresos" stroke="var(--c1)" strokeWidth={2} dot={false} connectNulls />
              <Line type="monotone" dataKey="gastos" stroke="var(--c4)" strokeWidth={2} dot={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
          <div className="flex items-center gap-4 mt-1 text-xs text-muted">
            <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 rounded" style={{ background: "var(--c1)" }} /> {t("macro.fiscalIngresos")}</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 rounded" style={{ background: "var(--c4)" }} /> {t("macro.fiscalGastos")}</span>
          </div>
        </Card>

        <Card>
          <CardHead
            icon={Landmark}
            title={t("macro.fiscalRecaudTitle")}
            subtitle={t("macro.fiscalRecaudSubtitle", { period: pulse.recaudacion?.period ?? "", unit: pulse.recaudacion_unit ?? "RD$" })}
          />
          {groups.length ? (
            <div className="space-y-2.5 mt-1">
              {groups.map((g) => (
                <div key={g.slug} className="flex items-center gap-3">
                  <span className="w-28 shrink-0 text-xs text-ink truncate" title={g.label}>{g.label}</span>
                  <div className="flex-1 h-3 rounded-full bg-surface2 overflow-hidden">
                    <div className="h-full rounded-full bg-accent" style={{ width: `${(g.value / maxRec) * 100}%` }} />
                  </div>
                  <span className="w-24 shrink-0 text-right mono text-xs text-body tabular-nums">
                    {fmtNum(g.value / 1e6, 0)} MM
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <StateBlock kind="empty" message={t("macro.fiscalRecaudEmpty")} />
          )}
        </Card>
      </div>

      <AiInsightCard
        title={t("macro.fiscalInsightTitle")}
        subtitle={t("macro.fiscalInsightSubtitle", { period: pulse.latest_period ?? "" })}
        icon={Landmark}
        depsKey={`fiscal:${pulse.latest_period ?? ""}:${audience}`}
        fetcher={() => getFiscalInsight(audience)}
        deepFetcher={(deep) => getFiscalInsight(audience, deep)}
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

      <p className="flex items-center gap-1.5 text-xs text-faint">
        <RefreshCw className="w-3 h-3" /> {t("macro.fiscalSource")}
      </p>
    </div>
  );
}

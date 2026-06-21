import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ShieldCheck, RefreshCw, AlertTriangle, BarChart3 } from "lucide-react";
import { Card, CardHead, StatTile, StateBlock, Chip } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { getSectorValidation, runSectorGateE, SectorGateEReport } from "../api";

function fmtDate(iso?: string): string {
  return iso
    ? new Date(iso).toLocaleString("es-DO", { dateStyle: "medium", timeStyle: "short" })
    : "—";
}
function fmtRho(x: number | null | undefined): string {
  return x == null ? "—" : (x >= 0 ? "+" : "") + x.toFixed(3);
}
function fmtPp(x: number | null | undefined): string {
  return x == null ? "—" : `${x >= 0 ? "+" : ""}${x.toFixed(2)} pp`;
}

/** A signal is "significant" only when the bootstrap CI excludes zero. */
function ciExcludesZero(ci?: [number | null, number | null]): boolean {
  if (!ci || ci[0] == null || ci[1] == null) return false;
  return (ci[0] > 0 && ci[1] > 0) || (ci[0] < 0 && ci[1] < 0);
}

/** Per-year Spearman as a centered diverging bar (−1 … +1). */
function YearBars({ rows }: { rows: NonNullable<SectorGateEReport["by_year"]> }) {
  return (
    <div className="space-y-2.5 mt-1">
      {rows.map((r) => {
        const v = r.spearman ?? 0;
        const w = Math.min(50, Math.abs(v) * 50);
        return (
          <div key={r.year} className="flex items-center gap-3">
            <span className="w-12 shrink-0 mono text-xs text-ink">{r.year}</span>
            <div className="relative flex-1 h-3 rounded-full bg-surface2 overflow-hidden">
              <div className="absolute left-1/2 top-0 h-full w-px bg-grid" />
              <div
                className="absolute top-0 h-full bg-accent"
                style={
                  v >= 0
                    ? { left: "50%", width: `${w}%` }
                    : { right: "50%", width: `${w}%` }
                }
              />
            </div>
            <span className="w-24 shrink-0 text-right mono text-xs text-body tabular-nums">
              {fmtRho(r.spearman)} <span className="text-faint">· n={r.n}</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function ValidationTab() {
  const { t } = useTranslation();
  const [report, setReport] = useState<SectorGateEReport | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [busy, setBusy] = useState(false);
  const poll = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      setReport(await getSectorValidation());
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
    return () => {
      if (poll.current) window.clearInterval(poll.current);
    };
  }, [load]);

  const stopPoll = () => {
    if (poll.current) {
      window.clearInterval(poll.current);
      poll.current = null;
    }
  };

  const regenerate = async () => {
    if (busy) return;
    stopPoll();
    setBusy(true);
    const before = report?.generated_at;
    try {
      const res = await runSectorGateE();
      if (!res.started) {
        setBusy(false);
        return;
      }
      let ticks = 0;
      poll.current = window.setInterval(async () => {
        ticks += 1;
        try {
          const r = await getSectorValidation();
          if (r.generated_at && r.generated_at !== before) {
            setReport(r);
            setBusy(false);
            stopPoll();
          } else if (ticks > 30) {
            setBusy(false);
            stopPoll();
          }
        } catch {
          setBusy(false);
          stopPoll();
        }
      }, 3000);
    } catch {
      setBusy(false);
      stopPoll();
    }
  };

  const regenBtn = (
    <button onClick={regenerate} disabled={busy} className="btn btn-ghost !py-1.5">
      <RefreshCw className={`w-3.5 h-3.5 ${busy ? "animate-spin" : ""}`} />
      {busy ? t("sector.valRegenBusy") : t("sector.valRegen")}
    </button>
  );

  if (status === "loading") return <StateBlock kind="loading" message={t("sector.valLoading")} />;
  if (status === "error") return <StateBlock kind="error" message={t("sector.valError")} />;
  if (!report?.has_report || report.has_data === false) {
    return (
      <div>
        <div className="flex justify-end mb-3">{regenBtn}</div>
        <StateBlock
          kind="empty"
          message={report?.reason ?? t("sector.valEmpty")}
        />
      </div>
    );
  }

  // Headline = mean yearly IC with a Student-t CI; significance = its CI excludes zero.
  const sig = ciExcludesZero(report.ic_ci);
  const ci = report.ic_ci;
  const pooledCi = report.spearman_pooled_ci;
  const qs = report.quintile_spread;

  return (
    <div>
      {/* Disclaimer honesto — prominente */}
      <div className="mb-4 flex items-start gap-2.5 rounded-[10px] bg-warn-soft p-3.5">
        <AlertTriangle className="w-4 h-4 text-warn shrink-0 mt-0.5" />
        <p className="text-xs text-body">
          <span className="font-semibold text-ink">{t("sector.valDisclaimerStrong")}</span>{" "}
          {report.disclaimer}
        </p>
      </div>

      <div className="flex items-center justify-between mb-3 gap-3">
        <span className="text-xs text-muted">
          {t("sector.valOutcomeLabel")} <span className="text-body">{report.outcome}</span> ·{" "}
          {report.resolution}
          {report.generated_at && <> · {fmtDate(report.generated_at)}</>}
        </span>
        {regenBtn}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-3">
        <StatTile label={t("sector.valStatIcMean")} value={fmtRho(report.mean_yearly_ic)} />
        <StatTile
          label={t("sector.valStatIcCi", { n: report.n_years ?? "—" })}
          value={ci && ci[0] != null ? `${fmtRho(ci[0])} … ${fmtRho(ci[1])}` : "—"}
        />
        <StatTile
          label={t("sector.valStatPartial")}
          value={`${fmtRho(report.spearman_partial_growth)}${
            report.spearman_partial_n ? ` · n=${report.spearman_partial_n}` : ""
          }`}
        />
        <StatTile
          label={t("sector.valStatObs")}
          value={t("sector.valObsValue", { n: fmtNum(report.n_observations, 0), branches: report.n_branches })}
        />
      </div>

      {/* Secundario, etiquetado: el ρ apilado (sobrestima la precisión) */}
      <p className="text-xs text-faint mb-5">
        {t("sector.valPooledPrefix", { rho: fmtRho(report.spearman_pooled) })}
        {pooledCi && pooledCi[0] != null && t("sector.valPooledCi", { lo: fmtRho(pooledCi[0]), hi: fmtRho(pooledCi[1]) })}
        {t("sector.valPooledMid")}
        <span className="text-muted">{t("sector.valPooledBold")}</span>
        {t("sector.valPooledSuffix")}
      </p>

      <div className="grid lg:grid-cols-3 gap-5">
        <Card className="lg:col-span-2">
          <CardHead
            icon={ShieldCheck}
            title={t("sector.valIcYearTitle")}
            subtitle={t("sector.valIcYearSubtitle", { y0: report.years?.[0], y1: report.years?.[1] })}
            right={
              <Chip tone={sig ? "ok" : "warn"}>
                {sig ? t("sector.valSigYes") : t("sector.valSigNo")}
              </Chip>
            }
          />
          {report.by_year && <YearBars rows={report.by_year} />}
          <p className="mt-3 text-xs text-muted">
            {sig ? (
              <>
                {t("sector.valSigYesPrefix")}<span className="font-medium">{t("sector.valSigYesBold")}</span>{t("sector.valSigYesSuffix")}
              </>
            ) : (
              <>
                {t("sector.valSigNoPrefix")}<span className="font-medium">{t("sector.valSigNoBold1")}</span>{t("sector.valSigNoMid")}
                <span className="font-medium">{t("sector.valSigNoBold2")}</span>{t("sector.valSigNoSuffix")}
              </>
            )}
          </p>
        </Card>

        <Card>
          <CardHead
            icon={BarChart3}
            title={t("sector.valQuintileTitle")}
            subtitle={t("sector.valQuintileSubtitle", { yearsPart: qs?.n_years ? ` (${qs.n_years})` : "" })}
          />
          {qs ? (
            <div className="space-y-3 mt-1">
              <StatTile label={t("sector.valQHigh")} value={fmtPp(qs.top_iai_mean_growth)} />
              <StatTile label={t("sector.valQLow")} value={fmtPp(qs.bottom_iai_mean_growth)} />
              <div className="border-t border-grid pt-3">
                <StatTile label={t("sector.valQSpread")} value={fmtPp(qs.spread)} />
              </div>
              <p className="text-xs text-muted">
                {t("sector.valQDirNote", { dir: qs.spread > 0 ? t("sector.valDirPositive") : t("sector.valDirNegative"), spread: fmtPp(qs.spread) })}
              </p>
            </div>
          ) : (
            <StateBlock kind="empty" message={t("sector.valQEmpty")} />
          )}
        </Card>
      </div>
    </div>
  );
}

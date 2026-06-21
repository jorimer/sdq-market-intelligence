import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ShieldCheck, RefreshCw, AlertTriangle, TrendingDown } from "lucide-react";
import { Card, CardHead, StatTile, StateBlock, Chip } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import {
  getTradeBacktest,
  runTradeBacktest,
  TradeBacktestReport,
  BacktestMetrics,
} from "../api";

function fmtPct(x: number | null | undefined): string {
  return x == null ? "—" : `${(x * 100).toFixed(0)}%`;
}
function fmtDate(iso?: string): string {
  return iso
    ? new Date(iso).toLocaleString("es-DO", { dateStyle: "medium", timeStyle: "short" })
    : "—";
}

function BandCurve({ m }: { m: BacktestMetrics }) {
  const maxRate = Math.max(0.0001, ...m.distress_by_band.map((r) => r.rate ?? 0));
  return (
    <div className="space-y-2.5 mt-1">
      {m.distress_by_band.map((r) => (
        <div key={r.tier} className="flex items-center gap-3">
          <span className="w-20 shrink-0 mono text-xs text-ink">{r.tier}</span>
          <div className="flex-1 h-3 rounded-full bg-surface2 overflow-hidden">
            <div
              className="h-full rounded-full bg-accent"
              style={{ width: `${((r.rate ?? 0) / maxRate) * 100}%` }}
            />
          </div>
          <span className="w-28 shrink-0 text-right mono text-xs text-body tabular-nums">
            {fmtPct(r.rate)} <span className="text-faint">· n={r.n}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

export function ValidationTab() {
  const { t } = useTranslation();
  const [report, setReport] = useState<TradeBacktestReport | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [busy, setBusy] = useState(false);
  const poll = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      setReport(await getTradeBacktest());
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
      const res = await runTradeBacktest();
      if (!res.started) {
        setBusy(false);
        return;
      }
      let ticks = 0;
      poll.current = window.setInterval(async () => {
        ticks += 1;
        try {
          const r = await getTradeBacktest();
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
      {busy ? t("trade.valRegenBusy") : t("trade.valRegen")}
    </button>
  );

  if (status === "loading") return <StateBlock kind="loading" message={t("trade.valLoading")} />;
  if (status === "error") return <StateBlock kind="error" message={t("trade.valError")} />;
  if (!report?.has_report || !report.export_collapse) {
    return (
      <div>
        <div className="flex justify-end mb-3">{regenBtn}</div>
        <StateBlock kind="empty" message={t("trade.valEmpty")} />
      </div>
    );
  }

  const prim = report.export_collapse; // PRIMARY — export-earnings collapse
  const contrast = report.external_macro; // SECONDARY — independent macro shock

  return (
    <div>
      {/* Disclaimer honesto — prominente */}
      <div className="mb-4 flex items-start gap-2.5 rounded-[10px] bg-warn-soft p-3.5">
        <AlertTriangle className="w-4 h-4 text-warn shrink-0 mt-0.5" />
        <p className="text-xs text-body">
          <span className="font-semibold text-ink">
            {t("trade.valDisclaimerStrong")}
          </span>{" "}
          {report.disclaimer}
        </p>
      </div>

      <div className="flex items-center justify-between mb-3 gap-3">
        <span className="text-xs text-muted">
          {t("trade.valOutcomeLabel")} <span className="text-body">{t("trade.valOutcomeValue")}</span>
          {t("trade.valOutcomeRest", { n: report.n_countries })}
          {report.generated_at && <> · {fmtDate(report.generated_at)}</>}
        </span>
        {regenBtn}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <StatTile label={t("trade.valStatGini")} value={prim.gini == null ? t("trade.na") : fmtNum(prim.gini, 3)} />
        <StatTile
          label={t("trade.valStatCi")}
          value={prim.gini_ci?.[0] != null ? `${fmtNum(prim.gini_ci[0], 2)} – ${fmtNum(prim.gini_ci[1], 2)}` : "—"}
        />
        <StatTile
          label={t("trade.valStatObs")}
          value={t("trade.valObsValue", { n: fmtNum(prim.n_observations, 0), countries: report.n_countries })}
        />
        <StatTile label={t("trade.valStatEvents")} value={`${prim.n_events} (${fmtPct(prim.event_rate)})`} />
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        <Card className="lg:col-span-2">
          <CardHead
            icon={ShieldCheck}
            title={t("trade.valCollapseTitle")}
            subtitle={t("trade.valCollapseSubtitle")}
            right={
              <Chip tone={prim.monotonic ? "ok" : "warn"}>
                {prim.monotonic ? t("trade.valMonotonic") : t("trade.valNotMonotonic")}
              </Chip>
            }
          />
          <BandCurve m={prim} />
          {prim.gini != null && prim.gini >= 0.2 ? (
            <p className="mt-3 text-xs text-muted">
              {t("trade.valDiscPrefix")}
              {prim.gini_ci && (prim.gini_ci[0] ?? 0) > 0 ? t("trade.valCiExcludes") : t("trade.valCiNarrow")}
              {t("trade.valDiscMid")}<span className="font-medium">{t("trade.valDiscBold")}</span>{t("trade.valDiscSuffix")}
            </p>
          ) : (
            <p className="mt-3 text-xs text-muted">
              {t("trade.valDiscWeakPrefix")}<span className="font-medium">{t("trade.valDiscWeakBold")}</span>{t("trade.valDiscWeakSuffix")}
            </p>
          )}
        </Card>

        <Card>
          <CardHead
            icon={TrendingDown}
            title={t("trade.valContrastTitle")}
            subtitle={t("trade.valContrastSubtitle")}
          />
          {contrast ? (
            <>
              <div className="grid grid-cols-2 gap-3 mb-3">
                <div>
                  <div className="text-xs text-muted">{t("trade.valContrastGini")}</div>
                  <div className="text-2xl font-display text-ink tabular-nums">
                    {contrast.gini == null ? "—" : fmtNum(contrast.gini, 3)}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-muted">{t("trade.valContrastCi")}</div>
                  <div className="text-sm font-display text-body tabular-nums mt-1.5">
                    {contrast.gini_ci?.[0] != null
                      ? `${fmtNum(contrast.gini_ci[0], 2)} – ${fmtNum(contrast.gini_ci[1], 2)}`
                      : "—"}
                  </div>
                </div>
              </div>
              <BandCurve m={contrast} />
              <p className="mt-3 pt-3 border-t border-line/60 text-[11px] text-faint">
                {t("trade.valContrastNotePrefix")}<span className="font-medium">{t("trade.valContrastNoBold")}</span>
                {t("trade.valContrastNoteSuffix", { events: contrast.n_events, obs: fmtNum(contrast.n_observations, 0) })}
              </p>
            </>
          ) : (
            <p className="text-xs text-muted">{t("trade.valContrastEmpty")}</p>
          )}
        </Card>
      </div>
    </div>
  );
}

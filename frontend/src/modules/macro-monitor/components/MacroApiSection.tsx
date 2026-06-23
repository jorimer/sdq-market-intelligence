import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
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
      setMsg({ tone: "ok", text: t("datos.macro.api.ingestOk") });
      await load();
    } catch (e: unknown) {
      const s = (e as { response?: { status?: number } })?.response?.status;
      setMsg({
        tone: "alert",
        text: s === 403 ? t("datos.macro.adminRequired") : t("datos.macro.api.ingestError"),
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
        text: t("datos.macro.api.backfillOk", { touched: r.touched.toLocaleString("es-DO"), min: r.period_min ?? "—", max: r.period_max ?? "—" }),
      });
      await load();
    } catch (e: unknown) {
      const s = (e as { response?: { status?: number } })?.response?.status;
      setMsg({
        tone: "alert",
        text:
          s === 403
            ? t("datos.macro.adminRequired")
            : s === 400
              ? t("datos.macro.api.backfillNoToken")
              : t("datos.macro.api.backfillError"),
      });
    } finally {
      setBusy("");
    }
  };

  if (status === "error") {
    return (
      <StateBlock
        kind="error"
        message={t("datos.macro.api.loadError")}
        action={
          <button className="btn btn-ghost" onClick={load}>
            {t("datos.macro.api.retry")}
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
        <StatTile label={t("datos.macro.api.statSeries")} value={items.length} />
        <StatTile label={t("datos.macro.api.statObs")} value={totalObs} />
        <StatTile label={t("datos.macro.api.statWithHistory")} value={withHistory} />
        <StatTile label={t("datos.macro.api.statSignals")} value={signals.length} />
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        <Card>
          <CardHead
            icon={Database}
            title={t("datos.macro.api.liveTitle")}
            subtitle={t("datos.macro.api.liveSub")}
          />
          <p className="text-sm text-muted mb-4">
            {t("datos.macro.api.liveNote")}
          </p>
          <button onClick={runLive} disabled={busy !== ""} className="btn btn-primary">
            <RefreshCw className={`w-4 h-4 ${busy === "live" ? "animate-spin" : ""}`} />
            {busy === "live" ? t("datos.macro.api.ingesting") : t("datos.macro.api.refreshLive")}
          </button>
        </Card>

        <Card>
          <CardHead
            icon={History}
            title={t("datos.macro.api.backfillTitle")}
            subtitle={t("datos.macro.api.backfillSub")}
          />
          <div className="flex items-end gap-3 mb-4">
            <label className="block">
              <span className="block text-xs font-medium text-muted mb-1">{t("datos.macro.api.from")}</span>
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
              <span className="block text-xs font-medium text-muted mb-1">{t("datos.macro.api.to")}</span>
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
            {busy === "backfill" ? t("datos.macro.api.running") : t("datos.macro.api.runBackfill")}
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
        <CardHead icon={ListTree} title={t("datos.macro.api.inventoryTitle")} subtitle={t("datos.macro.api.inventorySub", { count: items.length })} />
        {status === "loading" ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-8" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <StateBlock kind="empty" message={t("datos.macro.api.inventoryEmpty")} />
        ) : (
          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-line">
                  <th className="py-2 px-1 font-medium">{t("datos.macro.api.colSeries")}</th>
                  <th className="py-2 px-1 font-medium">{t("datos.macro.api.colUnit")}</th>
                  <th className="py-2 px-1 font-medium text-right">{t("datos.macro.api.colObs")}</th>
                  <th className="py-2 px-1 font-medium">{t("datos.macro.api.colLastPeriod")}</th>
                  <th className="py-2 px-1 font-medium text-right">{t("datos.macro.api.colLastValue")}</th>
                  <th className="py-2 px-1 font-medium">{t("datos.macro.api.colTrend")}</th>
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

import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Wrench, Trash2, Loader2, AlertTriangle } from "lucide-react";
import { Card, CardHead, Chip, StateBlock } from "@/shared/ui/primitives";
import { getIndicators, deleteSeries, MacroIndicator } from "@/modules/macro-monitor/api";

/** A code is an orphan of an old schema when its last dot-segment is a 4-digit year
 * (e.g. `bcrd.sector_externo.cuentas_corrientes.2023`): the parser used to emit one
 * code per year and now collapses them into a single annual series. */
function isOrphan(code: string): boolean {
  const last = code.split(".").pop() ?? "";
  return /^\d{4}$/.test(last);
}

/** Admin maintenance: delete a stale MacroSeries code left behind by a parser change.
 * `ingest_series` upserts by (series_code, period) and never prunes codes the parser
 * stopped emitting, so a schema change can leave orphan rows duplicating the monitor. */
export function SeriesMaintenanceSection() {
  const { t } = useTranslation();
  const [items, setItems] = useState<MacroIndicator[]>([]);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "alert"; text: string } | null>(null);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const ind = await getIndicators();
      setItems(ind);
      setSelected((cur) => (cur && ind.some((i) => i.series_code === cur) ? cur : ""));
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const orphans = items.filter((i) => isOrphan(i.series_code));

  async function remove() {
    if (!selected) return;
    if (!confirm(t("platform.series.confirmDelete", { code: selected }))) return;
    setBusy(true);
    setMsg(null);
    try {
      const deleted = await deleteSeries(selected);
      setMsg({
        tone: "ok",
        text:
          deleted > 0
            ? t("platform.series.deleted", { count: deleted, code: selected })
            : t("platform.series.deletedEmpty", { code: selected }),
      });
      setSelected("");
      await load();
    } catch {
      setMsg({ tone: "alert", text: t("platform.series.deleteError") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHead
        icon={Wrench}
        title={t("platform.series.title")}
        subtitle={t("platform.series.sub")}
      />

      {status === "loading" && <StateBlock kind="loading" />}

      {status === "error" && (
        <StateBlock
          kind="error"
          message={t("platform.series.loadError")}
          action={
            <button className="btn btn-soft" onClick={load}>
              {t("platform.series.retry")}
            </button>
          }
        />
      )}

      {status === "ready" && items.length === 0 && (
        <StateBlock kind="empty" message={t("platform.series.empty")} />
      )}

      {status === "ready" && items.length > 0 && (
        <div className="space-y-4">
          {orphans.length > 0 && (
            <div className="flex items-start gap-2 rounded-xl bg-alert-soft p-3">
              <AlertTriangle size={16} className="text-alert shrink-0 mt-0.5" />
              <div className="text-xs text-body">
                <span className="font-semibold text-ink">
                  {t("platform.series.orphansDetected", { count: orphans.length })}
                </span>{" "}
                {t("platform.series.orphanHint")}
                <ul className="mt-1 space-y-0.5">
                  {orphans.map((o) => (
                    <li key={o.series_code} className="mono text-faint">
                      {o.series_code}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-muted mb-1">{t("platform.series.seriesToDelete")}</label>
            <select
              className="field mono"
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
            >
              <option value="">{t("platform.series.chooseSeries")}</option>
              {items.map((i) => (
                <option key={i.series_code} value={i.series_code}>
                  {i.series_code}
                  {isOrphan(i.series_code) ? t("platform.series.orphanTag") : i.label ? `  · ${i.label}` : ""}
                </option>
              ))}
            </select>
          </div>

          {selected && isOrphan(selected) && (
            <Chip tone="alert">
              <AlertTriangle size={12} /> {t("platform.series.orphanChip")}
            </Chip>
          )}

          <div className="flex items-center gap-3">
            <button
              className="btn bg-alert text-white hover:brightness-95 disabled:opacity-50"
              disabled={!selected || busy}
              onClick={remove}
            >
              {busy ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
              {t("platform.series.deleteSeries")}
            </button>
            {msg && (
              <p className={`text-xs ${msg.tone === "alert" ? "text-alert" : "text-muted"}`}>
                {msg.text}
              </p>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

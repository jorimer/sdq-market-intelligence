import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { FileText, Download, Layers } from "lucide-react";
import { BankSelector } from "../components/BankSelector";
import { PageHead, Card, CardHead, Chip, StateBlock, Skeleton } from "@/shared/ui/primitives";
import { useEntityPeriodGuard } from "../components/EntityPeriodNotice";
import { useApp, periodToDate } from "@/shared/context/AppContext";
import {
  listReports,
  generateReport,
  downloadReport,
  listSystemReports,
  generateSystemReport,
  SYSTEM_REPORT_ES_ANUAL,
  SYSTEM_REPORT_TYPES,
  SYSTEM_REPORT_NEEDS_PERIOD,
  SystemReportType,
  anioDelInforme,
  ReportItem,
} from "../api";
import { mensajeDeError } from "../../../shared/api/errores";

// Los informes de ENTIDAD que se ofrecen. `revision_anual` mide un AÑO CALENDARIO y no un
// corte: el backend lee el AÑO del período y exige que haya cerrado (sin diciembre es un
// tramo, no un año). Lo vigila `test_regla_informe_de_entidad_pedible_desde_la_ui.py`.
const REPORT_TYPE_VALUES = ["full_rating", "scorecard", "communique", "revision_anual"];

/** Informes de entidad cuya unidad es el AÑO: el selector muestra cuál va a resumir. */
const REPORT_TYPE_ES_ANUAL: Record<string, boolean> = { revision_anual: true };

const STATUS_TONE: Record<string, "ok" | "warn" | "alert" | "muted"> = {
  completed: "ok",
  generating: "warn",
  error: "alert",
};

export function ReportsPage() {
  const { t } = useTranslation();
  const { period } = useApp();
  const periodEnd = periodToDate(period);
  const [bankId, setBankId] = useState("");
  const [bankName, setBankName] = useState("");
  const [reportType, setReportType] = useState("full_rating");
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const { blocked, notice } = useEntityPeriodGuard(bankId, bankName);
  // Informes de SISTEMA: no dependen de la entidad seleccionada, así que llevan su propio
  // estado y su propio listado (el de banco los filtra fuera — su `bank_id` es NULL).
  const [sysReports, setSysReports] = useState<ReportItem[]>([]);
  const [sysBusy, setSysBusy] = useState<string | null>(null);
  const [sysMsg, setSysMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const loadSystemReports = useCallback(() => {
    listSystemReports().then(setSysReports).catch(() => setSysReports([]));
  }, []);

  useEffect(() => { loadSystemReports(); }, [loadSystemReports]);

  const generateSystem = async (type: SystemReportType) => {
    setSysBusy(type);
    setSysMsg(null);
    try {
      await generateSystemReport(type, periodEnd);
      setSysMsg({ ok: true, text: t("banking.repMsgOk") });
      loadSystemReports();
    } catch (err: any) {
      setSysMsg({ ok: false, text: mensajeDeError(err, t("banking.repMsgErr")) });
    } finally {
      setSysBusy(null);
    }
  };

  const loadReports = useCallback((id: string) => {
    if (!id) return;
    setLoading(true);
    listReports(id)
      .then(setReports)
      .catch(() => setReports([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (bankId) loadReports(bankId);
  }, [bankId, loadReports]);

  const generate = async () => {
    if (!bankId) return;
    setGenerating(true);
    setMsg(null);
    try {
      await generateReport(bankId, periodEnd, reportType);
      setMsg({ ok: true, text: t("banking.repMsgOk") });
      loadReports(bankId);
    } catch (err: any) {
      setMsg({ ok: false, text: mensajeDeError(err, t("banking.repMsgErr")) });
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div>
      <PageHead
        eyebrow={t("banking.repEyebrow")}
        title={t("banking.repTitle")}
        sub={t("banking.repSub")}
      />

      <Card className="mb-5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-64">
            <label className="block text-xs font-medium text-muted mb-1">{t("banking.fieldEntity")}</label>
            <BankSelector value={bankId} onChange={(id, name) => { setBankId(id); setBankName(name); }} />
          </div>
          <div className="text-xs text-muted pb-2.5">
            {t("banking.periodLabel")} <span className="mono text-body">{periodEnd}</span>
          </div>
          <div className="w-48">
            <label className="block text-xs font-medium text-muted mb-1">{t("banking.repTypeLabel")}</label>
            <select value={reportType} onChange={(e) => setReportType(e.target.value)} className="field">
              {REPORT_TYPE_VALUES.map((value) => {
                // Un informe ANUAL descarta el trimestre del selector de período: se muestra
                // el año que va a resumir para que la relación se vea antes de generarlo.
                const anio = REPORT_TYPE_ES_ANUAL[value] ? anioDelInforme(periodEnd) : null;
                const etiqueta = t(`banking.repType.${value}`, value);
                return (
                  <option key={value} value={value}>
                    {anio ? `${etiqueta} · ${anio}` : etiqueta}
                  </option>
                );
              })}
            </select>
          </div>
          <button onClick={generate} disabled={!bankId || generating || blocked} className="btn btn-primary">
            <FileText className="w-4 h-4" />
            {generating ? t("banking.repBtnGenerating") : t("banking.repBtnGenerate")}
          </button>
        </div>
        {notice}
        {msg && (
          <div className={`mt-3 text-sm p-3 rounded-[10px] ${msg.ok ? "bg-ok-soft text-ok" : "bg-alert-soft text-alert"}`}>
            {msg.text}
          </div>
        )}
      </Card>

      <Card className="mb-5">
        <CardHead
          icon={Layers}
          title={t("banking.repSystemTitle")}
          subtitle={t("banking.repSystemSub")}
        />
        <div className="flex flex-wrap gap-2 mb-3">
          {SYSTEM_REPORT_TYPES.map((type) => (
            <button
              key={type}
              onClick={() => generateSystem(type)}
              disabled={sysBusy !== null}
              className="btn btn-ghost text-xs"
            >
              <FileText className="w-3.5 h-3.5" />
              {sysBusy === type
                ? t("banking.repBtnGenerating")
                : t(`banking.repType.${type}`, type)}
              {!SYSTEM_REPORT_NEEDS_PERIOD[type] && (
                <span className="text-muted ml-1">· {t("banking.repNoPeriod")}</span>
              )}
              {/* Un informe ANUAL descarta el trimestre del selector: se muestra el año que
                  va a resumir para que la relación entre lo elegido y lo que sale se vea. */}
              {SYSTEM_REPORT_ES_ANUAL[type] && anioDelInforme(periodEnd) && (
                <span className="text-muted ml-1 mono">· {anioDelInforme(periodEnd)}</span>
              )}
            </button>
          ))}
        </div>
        {sysMsg && (
          <div className={`mb-3 text-sm p-3 rounded-[10px] ${sysMsg.ok ? "bg-ok-soft text-ok" : "bg-alert-soft text-alert"}`}>
            {sysMsg.text}
          </div>
        )}
        {sysReports.length === 0 ? (
          <p className="text-sm text-muted py-4 text-center">{t("banking.repSystemEmpty")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted border-b border-line">
                <th className="py-2 px-2 font-medium">{t("banking.repColType")}</th>
                <th className="py-2 px-2 font-medium">{t("banking.repColPeriod")}</th>
                <th className="py-2 px-2 font-medium">{t("banking.repColStatus")}</th>
                <th className="py-2 px-2 font-medium text-right">{t("banking.repColAction")}</th>
              </tr>
            </thead>
            <tbody>
              {sysReports.map((r) => (
                <tr key={r.id} className="border-b border-line/60 last:border-0">
                  <td className="py-2.5 px-2 text-ink">{t(`banking.repType.${r.report_type}`, r.report_type ?? "—")}</td>
                  <td className="py-2.5 px-2 mono text-body">{r.period_end ?? "—"}</td>
                  <td className="py-2.5 px-2">
                    <Chip tone={STATUS_TONE[r.status ?? ""] ?? "muted"}>{r.status ?? "—"}</Chip>
                  </td>
                  <td className="py-2.5 px-2 text-right">
                    <button
                      onClick={() => downloadReport(r.id)}
                      disabled={r.status !== "completed"}
                      className="btn btn-ghost !py-1 !px-2.5 text-xs"
                    >
                      <Download className="w-3.5 h-3.5" /> PDF
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card>
        <CardHead icon={FileText} title={t("banking.repCardTitle")} subtitle={bankName || t("banking.repSelectEntity")} />
        {!bankId ? (
          <StateBlock kind="empty" message={t("banking.repEmptyNoEntity")} />
        ) : loading ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-10" />)}
          </div>
        ) : reports.length === 0 ? (
          <p className="text-sm text-muted py-6 text-center">{t("banking.repEmptyNoReports")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted border-b border-line">
                <th className="py-2 px-2 font-medium">{t("banking.repColType")}</th>
                <th className="py-2 px-2 font-medium">{t("banking.repColPeriod")}</th>
                <th className="py-2 px-2 font-medium">{t("banking.repColStatus")}</th>
                <th className="py-2 px-2 font-medium text-right">{t("banking.repColAction")}</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.id} className="border-b border-line/60 last:border-0">
                  <td className="py-2.5 px-2 text-ink">{t(`banking.repType.${r.report_type}`, r.report_type ?? "—")}</td>
                  <td className="py-2.5 px-2 mono text-body">{r.period_end ?? "—"}</td>
                  <td className="py-2.5 px-2">
                    <Chip tone={STATUS_TONE[r.status ?? ""] ?? "muted"}>{r.status ?? "—"}</Chip>
                  </td>
                  <td className="py-2.5 px-2 text-right">
                    <button
                      onClick={() => downloadReport(r.id)}
                      disabled={r.status !== "completed"}
                      className="btn btn-ghost !py-1 !px-2.5 text-xs"
                    >
                      <Download className="w-3.5 h-3.5" /> PDF
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

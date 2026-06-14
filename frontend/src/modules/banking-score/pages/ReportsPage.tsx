import { useEffect, useState, useCallback } from "react";
import { FileText, Download } from "lucide-react";
import { BankSelector } from "../components/BankSelector";
import { PageHead, Card, CardHead, Chip, StateBlock, Skeleton } from "@/shared/ui/primitives";
import { useEntityPeriodGuard } from "../components/EntityPeriodNotice";
import { useApp, periodToDate } from "@/shared/context/AppContext";
import {
  listReports,
  generateReport,
  downloadReport,
  ReportItem,
} from "../api";

const REPORT_TYPES = [
  { value: "full_rating", label: "Rating completo" },
  { value: "scorecard", label: "Scorecard" },
  { value: "communique", label: "Comunicado" },
];

const STATUS_TONE: Record<string, "ok" | "warn" | "alert" | "muted"> = {
  completed: "ok",
  generating: "warn",
  error: "alert",
};

export function ReportsPage() {
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
      setMsg({ ok: true, text: "Reporte generado." });
      loadReports(bankId);
    } catch (err: any) {
      setMsg({ ok: false, text: err?.response?.data?.detail || "No se pudo generar el reporte." });
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div>
      <PageHead
        eyebrow="SIB · reportes"
        title="Reportes"
        sub="Genera y descarga reportes de rating por entidad (full rating, scorecard, comunicado)."
      />

      <Card className="mb-5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-64">
            <label className="block text-xs font-medium text-muted mb-1">Entidad</label>
            <BankSelector value={bankId} onChange={(id, name) => { setBankId(id); setBankName(name); }} />
          </div>
          <div className="text-xs text-muted pb-2.5">
            Período <span className="mono text-body">{periodEnd}</span>
          </div>
          <div className="w-48">
            <label className="block text-xs font-medium text-muted mb-1">Tipo</label>
            <select value={reportType} onChange={(e) => setReportType(e.target.value)} className="field">
              {REPORT_TYPES.map((rt) => <option key={rt.value} value={rt.value}>{rt.label}</option>)}
            </select>
          </div>
          <button onClick={generate} disabled={!bankId || generating || blocked} className="btn btn-primary">
            <FileText className="w-4 h-4" />
            {generating ? "Generando…" : "Generar"}
          </button>
        </div>
        {notice}
        {msg && (
          <div className={`mt-3 text-sm p-3 rounded-[10px] ${msg.ok ? "bg-ok-soft text-ok" : "bg-alert-soft text-alert"}`}>
            {msg.text}
          </div>
        )}
      </Card>

      <Card>
        <CardHead icon={FileText} title="Reportes generados" subtitle={bankName || "Selecciona una entidad"} />
        {!bankId ? (
          <StateBlock kind="empty" message="Selecciona una entidad para ver y generar sus reportes." />
        ) : loading ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-10" />)}
          </div>
        ) : reports.length === 0 ? (
          <p className="text-sm text-muted py-6 text-center">Aún no hay reportes para esta entidad.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted border-b border-line">
                <th className="py-2 px-2 font-medium">Tipo</th>
                <th className="py-2 px-2 font-medium">Período</th>
                <th className="py-2 px-2 font-medium">Estado</th>
                <th className="py-2 px-2 font-medium text-right">Acción</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.id} className="border-b border-line/60 last:border-0">
                  <td className="py-2.5 px-2 text-ink">{r.report_type}</td>
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

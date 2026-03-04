import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { FileText } from "lucide-react";
import client from "@/shared/api/client";
import { BankSelector } from "../components/BankSelector";
import { ReportCard } from "../components/ReportCard";
import type { ReportEntry } from "@/types";

const REPORT_TYPES = [
  "full_rating",
  "scorecard",
  "communique",
  "datawatch",
  "wire",
  "criteria",
  "sector_outlook",
];

export function ReportsPage() {
  const { t } = useTranslation();
  const [bank, setBank] = useState("");
  const [period, setPeriod] = useState("");
  const [reportType, setReportType] = useState("full_rating");
  const [generating, setGenerating] = useState(false);
  const [history, setHistory] = useState<ReportEntry[]>([]);

  const fetchHistory = () => {
    client
      .get<ReportEntry[]>("/banking-score/reports/history")
      .then((r) => setHistory(r.data))
      .catch(() => {});
  };

  useEffect(() => {
    fetchHistory();
  }, []);

  const generate = async () => {
    if (!bank) return;
    setGenerating(true);
    try {
      const endpoint =
        reportType === "communique"
          ? "/banking-score/reports/communique"
          : reportType === "wire"
            ? "/banking-score/reports/wire"
            : reportType === "datawatch"
              ? "/banking-score/reports/datawatch"
              : reportType === "criteria"
                ? "/banking-score/reports/criteria"
                : reportType === "sector_outlook"
                  ? "/banking-score/reports/sector-outlook"
                  : "/banking-score/reports/generate";

      await client.post(endpoint, null, {
        params: { bank_name: bank, period: period || undefined, report_type: reportType },
      });
      fetchHistory();
    } catch (err) {
      console.error("Generate failed:", err);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-gray-900">{t("reports.title")}</h2>

      <div className="card">
        <div className="flex flex-wrap items-end gap-4">
          <div className="w-64">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t("reports.bank")}
            </label>
            <BankSelector value={bank} onChange={setBank} />
          </div>
          <div className="w-40">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t("reports.period")}
            </label>
            <input
              type="text"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="2024-Q4"
              className="input-field"
            />
          </div>
          <div className="w-52">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t("reports.type")}
            </label>
            <select
              value={reportType}
              onChange={(e) => setReportType(e.target.value)}
              className="input-field"
            >
              {REPORT_TYPES.map((rt) => (
                <option key={rt} value={rt}>
                  {t(`reports.types.${rt}`)}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={generate}
            disabled={!bank || generating}
            className="btn-primary flex items-center gap-2"
          >
            <FileText className="w-4 h-4" />
            {generating ? t("reports.generating") : t("reports.generate")}
          </button>
        </div>
      </div>

      <div>
        <h3 className="font-semibold text-gray-900 mb-4">{t("reports.history")}</h3>
        {history.length === 0 ? (
          <div className="card text-center py-8 text-gray-400">
            <p>{t("reports.noHistory")}</p>
          </div>
        ) : (
          <div className="space-y-3">
            {history.map((r) => (
              <ReportCard
                key={r.id}
                reportType={r.report_type}
                bankName={r.bank_name}
                period={r.period}
                createdAt={r.created_at}
                filePath={r.file_path}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

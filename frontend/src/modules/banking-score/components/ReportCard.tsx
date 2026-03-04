import { useTranslation } from "react-i18next";
import { FileText, Download } from "lucide-react";
import client from "@/shared/api/client";

interface Props {
  reportType: string;
  bankName: string;
  period: string;
  createdAt: string;
  filePath?: string;
}

export function ReportCard({
  reportType,
  bankName,
  period,
  createdAt,
  filePath,
}: Props) {
  const { t } = useTranslation();

  const handleDownload = async () => {
    if (!filePath) return;
    try {
      const resp = await client.get(`/banking-score/reports/download`, {
        params: { path: filePath },
        responseType: "blob",
      });
      const url = URL.createObjectURL(resp.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = filePath.split("/").pop() ?? "report.pdf";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Download failed:", err);
    }
  };

  return (
    <div className="card flex items-center gap-4">
      <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
        <FileText className="w-5 h-5 text-primary" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="font-medium text-gray-900 truncate">
          {t(`reports.types.${reportType}`, reportType)}
        </p>
        <p className="text-xs text-gray-500">
          {bankName} &middot; {period} &middot;{" "}
          {new Date(createdAt).toLocaleDateString()}
        </p>
      </div>
      {filePath && (
        <button
          onClick={handleDownload}
          className="btn-secondary flex items-center gap-1 text-xs"
        >
          <Download className="w-3.5 h-3.5" />
          {t("reports.download")}
        </button>
      )}
    </div>
  );
}

import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Upload, Download, Database, RefreshCw, HardDrive } from "lucide-react";
import { useDropzone } from "react-dropzone";
import client from "@/shared/api/client";
import { BankSelector } from "../components/BankSelector";
import { LoadingSkeleton } from "@/shared/components/LoadingSkeleton";
import type { DataStats } from "@/types";

interface SyncStatus {
  is_running: boolean;
  last_sync: string | null;
  next_scheduled: string | null;
  alerts: string[];
}

interface RawPeriod {
  id: number;
  period_end: string;
  period_type: string;
  source: string;
  created_at: string | null;
}

export function DataPage() {
  const { t } = useTranslation();
  const [stats, setStats] = useState<DataStats | null>(null);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [syncing, setSyncing] = useState(false);

  const [rawBank, setRawBank] = useState("");
  const [rawData, setRawData] = useState<RawPeriod[]>([]);
  const [rawLoading, setRawLoading] = useState(false);

  const refresh = () => {
    client.get<DataStats>("/banking-score/data/stats").then((r) => setStats(r.data)).catch(() => {});
    client.get<SyncStatus>("/banking-score/data/sync-status").then((r) => setSyncStatus(r.data)).catch(() => {});
  };

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (!rawBank) return;
    setRawLoading(true);
    client
      .get<{ periods: RawPeriod[] }>(`/banking-score/data/${rawBank}/raw`)
      .then((r) => setRawData(r.data.periods))
      .catch(() => setRawData([]))
      .finally(() => setRawLoading(false));
  }, [rawBank]);

  const onDrop = useCallback(async (files: File[]) => {
    if (files.length === 0) return;
    setUploading(true);
    setUploadMsg(null);
    const form = new FormData();
    form.append("file", files[0]);
    try {
      const { data } = await client.post("/banking-score/data/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setUploadMsg({ ok: true, text: data.message || "Upload exitoso" });
      refresh();
    } catch (err: any) {
      setUploadMsg({ ok: false, text: err?.response?.data?.detail || "Error al subir" });
    } finally {
      setUploading(false);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "text/csv": [".csv"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"] },
    maxFiles: 1,
  });

  const downloadTemplate = () => {
    client
      .get("/banking-score/data/template", { responseType: "blob" })
      .then((r) => {
        const url = URL.createObjectURL(r.data);
        const a = document.createElement("a");
        a.href = url;
        a.download = "sdq_banking_template.csv";
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch(() => {});
  };

  const triggerSync = async () => {
    setSyncing(true);
    try {
      await client.post("/banking-score/data/sib-sync");
      refresh();
    } catch {
      // silent
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-ink">{t("data.title")}</h2>

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="card flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-accent-soft flex items-center justify-center">
              <Database className="w-5 h-5 text-ink" />
            </div>
            <div>
              <p className="text-sm text-muted">{t("data.records")}</p>
              <p className="text-xl font-bold text-ink">{stats.total_records}</p>
            </div>
          </div>
          <div className="card flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-ok-soft flex items-center justify-center">
              <HardDrive className="w-5 h-5 text-ok" />
            </div>
            <div>
              <p className="text-sm text-muted">{t("data.banks")}</p>
              <p className="text-xl font-bold text-ink">{stats.total_banks}</p>
            </div>
          </div>
          <div className="card flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-warn-soft flex items-center justify-center">
              <RefreshCw className="w-5 h-5 text-warn" />
            </div>
            <div>
              <p className="text-sm text-muted">{t("data.periods")}</p>
              <p className="text-xl font-bold text-ink">{stats.periods.length}</p>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Upload section */}
        <div className="card space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-ink">{t("data.upload")}</h3>
            <button onClick={downloadTemplate} className="text-sm text-ink hover:underline flex items-center gap-1">
              <Download className="w-3.5 h-3.5" />
              Template CSV
            </button>
          </div>

          <div
            {...getRootProps()}
            className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
              isDragActive ? "border-accent bg-accent-soft" : "border-linestrong hover:border-accent"
            }`}
          >
            <input {...getInputProps()} />
            <Upload className="w-8 h-8 mx-auto mb-3 text-faint" />
            <p className="text-sm text-muted">{t("data.dropzone")}</p>
          </div>

          {uploading && (
            <div className="flex items-center gap-2 text-sm text-ink">
              <RefreshCw className="w-4 h-4 animate-spin" />
              {t("data.uploading")}
            </div>
          )}

          {uploadMsg && (
            <div className={`text-sm p-3 rounded-lg ${uploadMsg.ok ? "bg-ok-soft text-ok" : "bg-alert-soft text-alert"}`}>
              {uploadMsg.text}
            </div>
          )}
        </div>

        {/* SIB Sync */}
        <div className="card space-y-4">
          <h3 className="font-semibold text-ink">{t("data.sibSync")}</h3>
          {syncStatus ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted">{t("data.lastSync")}</span>
                <span className="font-medium text-ink">
                  {syncStatus.last_sync || "—"}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted">Estado</span>
                <span className={`font-medium ${syncStatus.is_running ? "text-warn" : "text-ok"}`}>
                  {syncStatus.is_running ? "En progreso" : "Inactivo"}
                </span>
              </div>
              {syncStatus.alerts.length > 0 && (
                <div className="space-y-1">
                  {syncStatus.alerts.map((a, i) => (
                    <div key={i} className="text-xs text-warn bg-warn-soft px-2 py-1 rounded">
                      {a}
                    </div>
                  ))}
                </div>
              )}
              <button
                onClick={triggerSync}
                disabled={syncing || syncStatus.is_running}
                className="btn-primary flex items-center gap-2 w-full justify-center"
              >
                <RefreshCw className={`w-4 h-4 ${syncing ? "animate-spin" : ""}`} />
                {syncing ? "Sincronizando..." : "Sincronizar con SIB"}
              </button>
            </div>
          ) : (
            <LoadingSkeleton rows={4} />
          )}
        </div>
      </div>

      {/* Raw data viewer */}
      <div className="card space-y-4">
        <h3 className="font-semibold text-ink">{t("data.rawData")}</h3>
        <div className="w-64">
          <BankSelector value={rawBank} onChange={setRawBank} />
        </div>

        {rawBank && rawLoading && <LoadingSkeleton rows={5} />}

        {rawBank && !rawLoading && rawData.length === 0 && (
          <p className="text-sm text-faint text-center py-6">{t("common.noData")}</p>
        )}

        {rawData.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line">
                  <th className="text-left py-2 px-3 font-medium text-muted">ID</th>
                  <th className="text-left py-2 px-3 font-medium text-muted">{t("rankings.period")}</th>
                  <th className="text-left py-2 px-3 font-medium text-muted">Tipo</th>
                  <th className="text-left py-2 px-3 font-medium text-muted">Fuente</th>
                  <th className="text-left py-2 px-3 font-medium text-muted">{t("reports.date")}</th>
                </tr>
              </thead>
              <tbody>
                {rawData.map((r) => (
                  <tr key={r.id} className="border-b border-line hover:bg-surface2">
                    <td className="py-2 px-3 text-faint">#{r.id}</td>
                    <td className="py-2 px-3 font-medium text-ink">{r.period_end}</td>
                    <td className="py-2 px-3 text-body">{r.period_type}</td>
                    <td className="py-2 px-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        r.source === "sib" ? "bg-accent-soft text-ink" : "bg-surface2 text-body"
                      }`}>
                        {r.source}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-muted">{r.created_at?.slice(0, 10) ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

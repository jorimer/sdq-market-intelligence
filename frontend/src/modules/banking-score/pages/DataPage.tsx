import { useState, useEffect, useCallback } from "react";
import { Upload, Download, RefreshCw } from "lucide-react";
import { useDropzone } from "react-dropzone";
import client from "@/shared/api/client";
import { BankSelector } from "../components/BankSelector";
import { PageHead, Card, CardHead, StatTile, Skeleton } from "@/shared/ui/primitives";
import { getStats, listPeriods, BankStats } from "../api";

interface SyncStatus {
  is_running: boolean;
  last_sync: string | null;
  last_check?: string | null;
  next_scheduled: string | null;
  backfill_done?: boolean;
  last_sync_result?: {
    status?: string;
    entities_matched?: number;
    records_created?: number;
    records_updated?: number;
  } | null;
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
  const [stats, setStats] = useState<BankStats | null>(null);
  const [periodCount, setPeriodCount] = useState(0);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const [rawBank, setRawBank] = useState("");
  const [rawData, setRawData] = useState<RawPeriod[]>([]);
  const [rawLoading, setRawLoading] = useState(false);

  const refresh = () => {
    getStats().then(setStats).catch(() => {});
    listPeriods().then((p) => setPeriodCount(p.length)).catch(() => {});
    client.get<SyncStatus>("/banking-score/data/sync-status").then((r) => setSyncStatus(r.data)).catch(() => {});
  };

  useEffect(refresh, []);

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
    if (!files.length) return;
    setUploading(true);
    setUploadMsg(null);
    const form = new FormData();
    form.append("file", files[0]);
    try {
      const { data } = await client.post("/banking-score/data/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setUploadMsg({ ok: true, text: data.message || "Carga exitosa." });
      refresh();
    } catch (err: any) {
      setUploadMsg({ ok: false, text: err?.response?.data?.detail || "Error al subir." });
    } finally {
      setUploading(false);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "text/csv": [".csv"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
    },
    maxFiles: 1,
  });

  const downloadTemplate = () => {
    client.get("/banking-score/data/template", { responseType: "blob" }).then((r) => {
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = "sdq_banking_template.csv";
      a.click();
      URL.revokeObjectURL(url);
    }).catch(() => {});
  };

  const triggerBackfill = async (force: boolean) => {
    setSyncing(true);
    setActionMsg(null);
    try {
      const { data } = await client.post(`/banking-score/data/sib-backfill?force=${force}`);
      setActionMsg(data.message || "Proceso iniciado.");
      refresh();
    } catch (err: any) {
      setActionMsg(err?.response?.data?.detail || "Error al iniciar el backfill.");
    } finally {
      setSyncing(false);
    }
  };

  const seedBanks = async () => {
    setSeeding(true);
    setActionMsg(null);
    try {
      const { data } = await client.post("/banking-score/data/seed-banks");
      setActionMsg(data?.detail ? "Seed completado." : "Seed ejecutado.");
      refresh();
    } catch (err: any) {
      setActionMsg(err?.response?.data?.detail || "Error en el seed.");
    } finally {
      setSeeding(false);
    }
  };

  // Poll status while a sync/backfill is running so the UI updates live.
  useEffect(() => {
    if (!syncStatus?.is_running) return;
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [syncStatus?.is_running]);

  return (
    <div>
      <PageHead
        eyebrow="SIB · SIMBAD"
        title="Datos"
        sub="Carga, sincronización y exploración de los estados financieros por entidad."
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <StatTile label="Registros" value={stats?.total_records ?? 0} />
        <StatTile label="Entidades" value={stats?.total_entities ?? 0} />
        <StatTile label="Períodos" value={periodCount} />
        <StatTile label="Ratings" value={stats?.total_ratings ?? 0} />
      </div>

      <div className="grid lg:grid-cols-2 gap-5 mb-5">
        <Card>
          <CardHead
            icon={Upload}
            title="Cargar datos"
            right={
              <button onClick={downloadTemplate} className="text-sm text-accent-ink hover:underline flex items-center gap-1">
                <Download className="w-3.5 h-3.5" /> Plantilla CSV
              </button>
            }
          />
          <div
            {...getRootProps()}
            className={`border-2 border-dashed rounded-[10px] p-8 text-center cursor-pointer transition-colors ${
              isDragActive ? "border-accent bg-accent-soft" : "border-linestrong hover:border-accent"
            }`}
          >
            <input {...getInputProps()} />
            <Upload className="w-8 h-8 mx-auto mb-3 text-faint" />
            <p className="text-sm text-muted">Arrastra un CSV/XLSX o haz clic para seleccionar.</p>
          </div>
          {uploading && (
            <div className="flex items-center gap-2 text-sm text-body mt-3">
              <RefreshCw className="w-4 h-4 animate-spin" /> Subiendo…
            </div>
          )}
          {uploadMsg && (
            <div className={`mt-3 text-sm p-3 rounded-[10px] ${uploadMsg.ok ? "bg-ok-soft text-ok" : "bg-alert-soft text-alert"}`}>
              {uploadMsg.text}
            </div>
          )}
        </Card>

        <Card>
          <CardHead
            icon={RefreshCw}
            title="Sincronización SIB"
            subtitle="Reemplaza datos de muestra por datos reales de la API del SIB"
            right={
              <span className={`chip ${syncStatus?.is_running ? "text-warn" : "text-ok"}`}>
                {syncStatus?.is_running ? "En progreso" : "Inactivo"}
              </span>
            }
          />
          {syncStatus ? (
            <div className="space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-muted">Última sincronización</span>
                <span className="mono text-ink">{syncStatus.last_sync?.slice(0, 19).replace("T", " ") || "—"}</span>
              </div>
              {syncStatus.last_sync_result && (
                <div className="text-xs text-muted">
                  Último resultado: {syncStatus.last_sync_result.status} ·{" "}
                  {syncStatus.last_sync_result.entities_matched ?? 0} entidades ·{" "}
                  {(syncStatus.last_sync_result.records_created ?? 0) + (syncStatus.last_sync_result.records_updated ?? 0)} registros
                </div>
              )}
              {actionMsg && <div className="text-xs text-body bg-surface2 px-3 py-2 rounded-[10px]">{actionMsg}</div>}
              {syncStatus.alerts?.slice(-3).map((a, i) => (
                <div key={i} className="text-xs text-warn bg-warn-soft px-2 py-1 rounded">{a}</div>
              ))}
              <div className="flex flex-wrap gap-2 pt-1">
                <button
                  onClick={() => triggerBackfill(false)}
                  disabled={syncing || syncStatus.is_running}
                  className="btn btn-primary justify-center"
                >
                  <RefreshCw className={`w-4 h-4 ${syncing ? "animate-spin" : ""}`} />
                  {syncing ? "Iniciando…" : "Sincronizar con SIB"}
                </button>
                <button
                  onClick={() => triggerBackfill(true)}
                  disabled={syncing || syncStatus.is_running}
                  className="btn btn-ghost justify-center"
                  title="Reemplaza todos los registros con datos reales del SIB"
                >
                  Backfill (forzar)
                </button>
                <button
                  onClick={seedBanks}
                  disabled={seeding || syncStatus.is_running}
                  className="btn btn-ghost justify-center"
                  title="Crea las 35 entidades + datos históricos de muestra"
                >
                  {seeding ? "Sembrando…" : "Sembrar bancos"}
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-2">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-8" />)}</div>
          )}
        </Card>
      </div>

      <Card>
        <CardHead title="Explorar datos crudos" subtitle="Períodos cargados por entidad" />
        <div className="w-64 mb-4">
          <BankSelector value={rawBank} onChange={(id) => setRawBank(id)} />
        </div>
        {rawBank && rawLoading ? (
          <div className="space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-8" />)}</div>
        ) : rawBank && rawData.length === 0 ? (
          <p className="text-sm text-muted py-4 text-center">Sin registros para esta entidad.</p>
        ) : rawData.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-line">
                  <th className="py-2 px-2 font-medium">Período</th>
                  <th className="py-2 px-2 font-medium">Tipo</th>
                  <th className="py-2 px-2 font-medium">Fuente</th>
                  <th className="py-2 px-2 font-medium text-right">Creado</th>
                </tr>
              </thead>
              <tbody>
                {rawData.map((r) => (
                  <tr key={r.id} className="border-b border-line/60 last:border-0">
                    <td className="py-2.5 px-2 mono text-ink">{r.period_end}</td>
                    <td className="py-2.5 px-2 text-body">{r.period_type}</td>
                    <td className="py-2.5 px-2">
                      <span className="text-xs px-2 py-0.5 rounded-full bg-surface2 text-body">{r.source}</span>
                    </td>
                    <td className="py-2.5 px-2 text-right mono text-xs text-muted">{r.created_at?.slice(0, 10) ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>
    </div>
  );
}

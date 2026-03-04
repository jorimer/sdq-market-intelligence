import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Brain, CheckCircle, XCircle, RefreshCw } from "lucide-react";
import client from "@/shared/api/client";
import { LoadingSkeleton } from "@/shared/components/LoadingSkeleton";
import type { ModelStatus } from "@/types";

export function ModelPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [training, setTraining] = useState(false);
  const [trainResult, setTrainResult] = useState<{ ok: boolean; text: string } | null>(null);

  const fetchStatus = () => {
    setLoading(true);
    client
      .get<ModelStatus>("/banking-score/model/status")
      .then((r) => setStatus(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  const train = async () => {
    setTraining(true);
    setTrainResult(null);
    try {
      const { data } = await client.post("/banking-score/model/train");
      setTrainResult({ ok: true, text: data.message || "Modelo entrenado exitosamente" });
      fetchStatus();
    } catch (err: any) {
      setTrainResult({ ok: false, text: err?.response?.data?.detail || "Error al entrenar" });
    } finally {
      setTraining(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <h2 className="text-xl font-bold text-gray-900">{t("model.title")}</h2>
        <div className="card">
          <LoadingSkeleton rows={6} />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-gray-900">{t("model.title")}</h2>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Model Status */}
        <div className="card space-y-5">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
              <Brain className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h3 className="font-semibold text-gray-900">{t("model.status")}</h3>
              <div className="flex items-center gap-1.5 mt-0.5">
                {status?.ml_available ? (
                  <>
                    <CheckCircle className="w-4 h-4 text-success" />
                    <span className="text-sm text-success font-medium">{t("model.available")}</span>
                  </>
                ) : (
                  <>
                    <XCircle className="w-4 h-4 text-danger" />
                    <span className="text-sm text-danger font-medium">{t("model.unavailable")}</span>
                  </>
                )}
              </div>
            </div>
          </div>

          <div className="space-y-3">
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">{t("model.type")}</span>
              <span className="font-medium text-gray-900">{status?.model_type ?? "—"}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">{t("model.version")}</span>
              <span className="font-medium text-gray-900">{status?.model_version ?? "—"}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">{t("model.trainingSamples")}</span>
              <span className="font-medium text-gray-900">{status?.training_records ?? 0}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">{t("model.totalRatings")}</span>
              <span className="font-medium text-gray-900">{status?.total_ratings ?? 0}</span>
            </div>
          </div>
        </div>

        {/* Metrics */}
        <div className="card space-y-5">
          <h3 className="font-semibold text-gray-900">Metricas del Modelo</h3>

          {status?.model_metrics ? (
            <div className="grid grid-cols-2 gap-4">
              <MetricCard
                label={t("model.accuracy")}
                value={`${(status.model_metrics.accuracy * 100).toFixed(1)}%`}
                color="text-success"
              />
              <MetricCard
                label={t("model.kappa")}
                value={status.model_metrics.kappa.toFixed(3)}
                color="text-primary"
              />
              <MetricCard
                label="N Train"
                value={String(status.model_metrics.n_train)}
                color="text-gray-700"
              />
              <MetricCard
                label="N Test"
                value={String(status.model_metrics.n_test)}
                color="text-gray-700"
              />
            </div>
          ) : (
            <div className="text-center py-8 text-gray-400">
              <Brain className="w-10 h-10 mx-auto mb-2 opacity-30" />
              <p className="text-sm">No hay metricas disponibles. Entrene el modelo primero.</p>
            </div>
          )}
        </div>
      </div>

      {/* Train section */}
      <div className="card">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div>
            <h3 className="font-semibold text-gray-900">{t("model.train")}</h3>
            <p className="text-sm text-gray-500 mt-1">{t("model.minRecords")}</p>
          </div>
          <button
            onClick={train}
            disabled={training || !status?.can_train}
            className="btn-primary flex items-center gap-2"
          >
            <RefreshCw className={`w-4 h-4 ${training ? "animate-spin" : ""}`} />
            {training ? t("model.training") : t("model.train")}
          </button>
        </div>

        {!status?.can_train && !training && (
          <div className="mt-3 text-sm text-warning bg-warning/10 px-3 py-2 rounded-lg">
            Se necesitan al menos {status?.min_records_for_training ?? 30} registros para entrenar.
            Actualmente: {status?.training_records ?? 0}.
          </div>
        )}

        {trainResult && (
          <div className={`mt-3 text-sm p-3 rounded-lg ${trainResult.ok ? "bg-success/10 text-success" : "bg-danger/10 text-danger"}`}>
            {trainResult.text}
          </div>
        )}
      </div>
    </div>
  );
}

function MetricCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="bg-gray-50 rounded-lg p-4 text-center">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
    </div>
  );
}

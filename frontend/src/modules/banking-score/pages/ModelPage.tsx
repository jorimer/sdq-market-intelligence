import { useState, useEffect } from "react";
import { Brain, CheckCircle, XCircle, RefreshCw } from "lucide-react";
import client from "@/shared/api/client";
import { PageHead, Card, CardHead, StatTile, StateBlock, LoadingGrid } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import type { ModelStatus } from "@/types";

export function ModelPage() {
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

  useEffect(fetchStatus, []);

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

  const head = (
    <PageHead
      eyebrow="XGBoost"
      title="Modelo ML"
      sub="Complemento explicable al núcleo determinista (contribuciones por variable), no oráculo."
    />
  );

  if (loading) return <div>{head}<LoadingGrid /></div>;

  const m = status?.model_metrics;

  return (
    <div>
      {head}

      <div className="grid lg:grid-cols-2 gap-5 mb-5">
        <Card>
          <CardHead
            icon={Brain}
            title="Estado del modelo"
            right={
              status?.ml_available ? (
                <span className="inline-flex items-center gap-1.5 text-sm text-ok font-medium">
                  <CheckCircle className="w-4 h-4" /> Disponible
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 text-sm text-alert font-medium">
                  <XCircle className="w-4 h-4" /> No disponible
                </span>
              )
            }
          />
          <div className="space-y-2.5">
            {[
              ["Tipo", status?.model_type ?? "—"],
              ["Versión", status?.model_version ?? "—"],
              ["Muestras de entrenamiento", status?.training_records ?? 0],
              ["Ratings totales", status?.total_ratings ?? 0],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between text-sm border-b border-line/60 pb-2 last:border-0">
                <span className="text-muted">{k}</span>
                <span className="mono text-ink">{v}</span>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <CardHead title="Métricas" subtitle="Desempeño en validación" />
          {m ? (
            <div className="grid grid-cols-2 gap-3">
              <StatTile label="Accuracy" value={fmtNum(m.accuracy * 100, 1)} unit="%" />
              <StatTile label="Kappa" value={fmtNum(m.kappa, 3)} />
              <StatTile label="N entrenamiento" value={m.n_train} />
              <StatTile label="N prueba" value={m.n_test} />
            </div>
          ) : (
            <p className="text-sm text-muted py-6 text-center">
              Sin métricas. Entrena el modelo primero.
            </p>
          )}
        </Card>
      </div>

      <Card>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="min-w-0">
            <h3 className="font-display text-[15px] font-bold text-ink">Entrenar modelo</h3>
            <p className="text-sm text-muted mt-1">
              Requiere ≥ {status?.min_records_for_training ?? 30} ratings; actualmente {status?.training_records ?? 0}.
            </p>
          </div>
          <button onClick={train} disabled={training || !status?.can_train} className="btn btn-primary shrink-0">
            <RefreshCw className={`w-4 h-4 ${training ? "animate-spin" : ""}`} />
            {training ? "Entrenando…" : "Entrenar"}
          </button>
        </div>
        {trainResult && (
          <div className={`mt-3 text-sm p-3 rounded-[10px] ${trainResult.ok ? "bg-ok-soft text-ok" : "bg-alert-soft text-alert"}`}>
            {trainResult.text}
          </div>
        )}
      </Card>
    </div>
  );
}

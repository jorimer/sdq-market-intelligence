import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Brain, CheckCircle, XCircle, RefreshCw } from "lucide-react";
import client from "@/shared/api/client";
import { PageHead, Card, CardHead, StatTile, LoadingGrid } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
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

  useEffect(fetchStatus, []);

  const train = async () => {
    setTraining(true);
    setTrainResult(null);
    try {
      const { data } = await client.post("/banking-score/model/train");
      setTrainResult({ ok: true, text: data.message || t("banking.mdlTrainOk") });
      fetchStatus();
    } catch (err: any) {
      setTrainResult({ ok: false, text: err?.response?.data?.detail || t("banking.mdlTrainErr") });
    } finally {
      setTraining(false);
    }
  };

  const head = (
    <PageHead
      eyebrow="XGBoost"
      title={t("banking.mdlTitle")}
      sub={t("banking.mdlSub")}
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
            title={t("banking.mdlStatusTitle")}
            right={
              status?.ml_available ? (
                <span className="inline-flex items-center gap-1.5 text-sm text-ok font-medium">
                  <CheckCircle className="w-4 h-4" /> {t("banking.mdlAvailable")}
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 text-sm text-alert font-medium">
                  <XCircle className="w-4 h-4" /> {t("banking.mdlUnavailable")}
                </span>
              )
            }
          />
          <div className="space-y-2.5">
            {[
              [t("banking.mdlRowType"), status?.model_type ?? "—"],
              [t("banking.mdlRowVersion"), status?.model_version ?? "—"],
              [t("banking.mdlRowTrainSamples"), status?.training_records ?? 0],
              [t("banking.mdlRowTotalRatings"), status?.total_ratings ?? 0],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between text-sm border-b border-line/60 pb-2 last:border-0">
                <span className="text-muted">{k}</span>
                <span className="mono text-ink">{v}</span>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <CardHead title={t("banking.mdlMetricsTitle")} subtitle={t("banking.mdlMetricsSubtitle")} />
          {m ? (
            <div className="grid grid-cols-2 gap-3">
              <StatTile label={t("banking.mdlAccuracy")} value={fmtNum(m.accuracy * 100, 1)} unit="%" />
              <StatTile label={t("banking.mdlKappa")} value={fmtNum(m.kappa, 3)} />
              <StatTile label={t("banking.mdlNTrain")} value={m.n_train} />
              <StatTile label={t("banking.mdlNTest")} value={m.n_test} />
            </div>
          ) : (
            <p className="text-sm text-muted py-6 text-center">
              {t("banking.mdlNoMetrics")}
            </p>
          )}
        </Card>
      </div>

      <Card>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="min-w-0">
            <h3 className="font-display text-[15px] font-bold text-ink">{t("banking.mdlTrainTitle")}</h3>
            <p className="text-sm text-muted mt-1">
              {t("banking.mdlTrainHint", {
                min: status?.min_records_for_training ?? 30,
                actual: status?.training_records ?? 0,
              })}
            </p>
          </div>
          <button onClick={train} disabled={training || !status?.can_train} className="btn btn-primary shrink-0">
            <RefreshCw className={`w-4 h-4 ${training ? "animate-spin" : ""}`} />
            {training ? t("banking.mdlBtnTraining") : t("banking.mdlBtnTrain")}
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

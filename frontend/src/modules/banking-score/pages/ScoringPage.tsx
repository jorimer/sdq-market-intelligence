import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Calculator, Radar as RadarIcon, ListChecks } from "lucide-react";
import { BankSelector } from "../components/BankSelector";
import { RadarChart } from "../components/RadarChart";
import { ScoreGauge } from "../components/ScoreGauge";
import { PerfilCompacto } from "../components/PerfilSDQ";
import { IndicatorTable } from "../components/IndicatorTable";
import { PageHead, Card, CardHead, StateBlock } from "@/shared/ui/primitives";
import { useEntityPeriodGuard } from "../components/EntityPeriodNotice";
import { fmtNum } from "@/shared/lib/format";
import { useApp, periodToDate } from "@/shared/context/AppContext";
import {
  runScoring,
  getModelStatus,
  ScoringResult,
  SUB_KEYS,
} from "../api";

type ModelMode = "deterministic" | "ml";

export function ScoringPage() {
  const { t } = useTranslation();
  const { period } = useApp();
  const periodEnd = periodToDate(period);
  const [bankId, setBankId] = useState("");
  const [bankName, setBankName] = useState("");
  const [result, setResult] = useState<ScoringResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [modelMode, setModelMode] = useState<ModelMode>("deterministic");
  const [mlAvailable, setMlAvailable] = useState(false);
  const { blocked, notice } = useEntityPeriodGuard(bankId, bankName);

  useEffect(() => {
    getModelStatus()
      .then((s) => setMlAvailable(!!s.ml_available))
      .catch(() => setMlAvailable(false));
  }, []);

  const run = async () => {
    if (!bankId) return;
    setLoading(true);
    setError(false);
    try {
      setResult(await runScoring(bankId, periodEnd, modelMode));
    } catch {
      setError(true);
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <PageHead
        eyebrow={t("banking.scoringEyebrow")}
        title={t("banking.scoringTitle")}
        sub={t("banking.scoringSub")}
      />

      <Card className="mb-5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-64">
            <label className="block text-xs font-medium text-muted mb-1">{t("banking.fieldEntity")}</label>
            <BankSelector
              value={bankId}
              onChange={(id, name) => {
                setBankId(id);
                setBankName(name);
              }}
            />
          </div>
          <div className="text-xs text-muted pb-2.5">
            {t("banking.scoringPeriod")} <span className="mono text-body">{periodEnd}</span>
          </div>
          <div className="pb-1">
            <label className="block text-xs font-medium text-muted mb-1">{t("banking.fieldModel")}</label>
            <div className="inline-flex rounded-lg border border-line bg-surface2 p-0.5">
              {(["deterministic", "ml"] as ModelMode[]).map((m) => {
                const disabled = m === "ml" && !mlAvailable;
                const active = modelMode === m;
                return (
                  <button
                    key={m}
                    type="button"
                    disabled={disabled}
                    onClick={() => setModelMode(m)}
                    title={disabled ? t("banking.modelMlDisabledTitle") : undefined}
                    className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
                      active ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink"
                    } ${disabled ? "opacity-40 cursor-not-allowed" : ""}`}
                  >
                    {m === "deterministic" ? t("banking.modelDeterministic") : t("banking.modelMl")}
                  </button>
                );
              })}
            </div>
          </div>
          <button onClick={run} disabled={!bankId || loading || blocked} className="btn btn-primary">
            <Calculator className="w-4 h-4" />
            {loading ? t("banking.calculating") : t("banking.calc")}
          </button>
        </div>
        {notice}
      </Card>

      {error ? (
        <StateBlock kind="error" message={t("banking.scoringError")} />
      ) : !result ? (
        <StateBlock kind="empty" message={t("banking.scoringEmpty")} />
      ) : (
        <div className="grid lg:grid-cols-3 gap-5">
          <Card className="flex flex-col items-center text-center">
            <div className="text-xs text-muted mb-2 w-full truncate">{bankName}</div>
            <ScoreGauge score={result.overall_score} size={150} />
            <div className="mt-3">
              <PerfilCompacto ejecucion={result.ejecucion} bandaEjecucion={result.banda_ejecucion}
                              resiliencia={result.resiliencia} bandaResiliencia={result.banda_resiliencia} />
            </div>
            <div className="mt-2 text-[11px] text-muted">
              {result.model === "ml"
                ? `${t("banking.scoringMlBadge")}${result.model_version ? " · v" + result.model_version : ""}`
                : t("banking.scoringDetBadge")}
            </div>
          </Card>

          <Card>
            <CardHead icon={RadarIcon} title={t("banking.subComponentsTitle")} subtitle={t("banking.subComponentsSubtitle")} />
            <RadarChart data={result.sub_components} />
          </Card>

          <Card>
            <CardHead title={t("banking.ponderTitle")} subtitle={t("banking.ponderSubtitle")} />
            <div className="space-y-3">
              {SUB_KEYS.map((key) => {
                const val = result.sub_components[key];
                return (
                  <div key={key}>
                    <div className="flex items-baseline justify-between mb-1">
                      <span className="text-sm text-ink truncate">{t(`sub.${key}`)}</span>
                      <span className="mono text-sm font-semibold text-ink">{fmtNum(val, 1)}</span>
                    </div>
                    <div className="h-2 rounded-full bg-surface2 overflow-hidden">
                      <div className="h-full rounded-full bg-accent" style={{ width: `${val}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>

          <Card className="lg:col-span-3">
            <CardHead icon={ListChecks} title={t("banking.indicatorsTitle")} subtitle={t("banking.indicatorsSubtitle")} />
            <IndicatorTable indicators={result.indicators ?? {}} bankId={bankId} />
          </Card>
        </div>
      )}
    </div>
  );
}

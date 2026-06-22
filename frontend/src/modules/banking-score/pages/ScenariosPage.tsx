import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Sliders, RotateCcw, Zap } from "lucide-react";
import { BankSelector } from "../components/BankSelector";
import { RadarChart } from "../components/RadarChart";
import { ScoreGauge } from "../components/ScoreGauge";
import { RatingBadge } from "../components/RatingBadge";
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import { PageHead, Card, CardHead, StateBlock, Delta } from "@/shared/ui/primitives";
import { useEntityPeriodGuard } from "../components/EntityPeriodNotice";
import { useApp, periodToDate } from "@/shared/context/AppContext";
import {
  runScoring,
  simulate,
  getScenarioInsight,
  ScoringResult,
  SubComponents,
  SUB_KEYS,
} from "../api";

const PRESETS: Record<string, SubComponents> = {
  Optimista: { solidez: 90, calidad: 85, eficiencia: 80, liquidez: 85, diversificacion: 80 },
  Base: { solidez: 65, calidad: 60, eficiencia: 55, liquidez: 60, diversificacion: 55 },
  Adverso: { solidez: 40, calidad: 35, eficiencia: 30, liquidez: 35, diversificacion: 30 },
  Estrés: { solidez: 25, calidad: 20, eficiencia: 15, liquidez: 20, diversificacion: 15 },
};

function fromResult(r: ScoringResult): SubComponents {
  return { ...r.sub_components };
}

export function ScenariosPage() {
  const { t } = useTranslation();
  const { period } = useApp();
  const periodEnd = periodToDate(period);
  const [bankId, setBankId] = useState("");
  const [bankName, setBankName] = useState("");
  const [base, setBase] = useState<ScoringResult | null>(null);
  const [sim, setSim] = useState<ScoringResult | null>(null);
  const [sliders, setSliders] = useState<SubComponents>({ ...PRESETS.Base });
  const [loading, setLoading] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const { blocked, notice } = useEntityPeriodGuard(bankId, bankName);

  const loadBase = async () => {
    if (!bankId) return;
    setLoading(true);
    try {
      const r = await runScoring(bankId, periodEnd);
      setBase(r);
      setSliders(fromResult(r));
      setSim(null);
    } catch {
      setBase(null);
    } finally {
      setLoading(false);
    }
  };

  const runSim = async () => {
    if (!bankId) return;
    setSimulating(true);
    try {
      setSim(await simulate(sliders, base?.entity_type ?? undefined));
    } catch {
      // silent
    } finally {
      setSimulating(false);
    }
  };

  return (
    <div>
      <PageHead
        eyebrow={t("banking.scenEyebrow")}
        title={t("banking.scenTitle")}
        sub={t("banking.scenSub")}
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
          <button onClick={loadBase} disabled={!bankId || loading || blocked} className="btn btn-primary">
            <Sliders className="w-4 h-4" />
            {loading ? t("banking.scenLoading") : t("banking.scenLoadBase")}
          </button>
        </div>
        {notice}
      </Card>

      {!base ? (
        <StateBlock kind="empty" message={t("banking.scenEmpty")} />
      ) : (
        <div className="grid lg:grid-cols-3 gap-5">
          {/* Sliders */}
          <Card>
            <CardHead title={t("banking.scenAdjustTitle")} subtitle={bankName} />
            <div className="space-y-4">
              {SUB_KEYS.map((key) => (
                <div key={key}>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-body">{t(`sub.${key}`)}</span>
                    <span className="mono font-semibold text-ink">{sliders[key].toFixed(1)}</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    step={0.5}
                    value={sliders[key]}
                    onChange={(e) => setSliders((s) => ({ ...s, [key]: parseFloat(e.target.value) }))}
                    className="w-full accent-accent"
                  />
                </div>
              ))}
            </div>
            <div className="mt-4">
              <p className="text-xs font-medium text-muted mb-2">{t("banking.scenPresetsLabel")}</p>
              <div className="grid grid-cols-2 gap-2">
                {Object.keys(PRESETS).map((p) => (
                  <button
                    key={p}
                    onClick={() => setSliders({ ...PRESETS[p] })}
                    className="text-xs px-2 py-1.5 rounded-[10px] border border-line hover:bg-surface2 text-body"
                  >
                    {t(`banking.scenPreset.${p}`, p)}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex gap-2 mt-4">
              <button onClick={runSim} disabled={simulating} className="btn btn-primary flex-1">
                <Zap className="w-4 h-4" />
                {simulating ? t("banking.scenSimulating") : t("banking.scenSimulate")}
              </button>
              <button
                onClick={() => { setSliders(fromResult(base)); setSim(null); }}
                className="btn btn-ghost"
                title={t("banking.scenResetTitle")}
              >
                <RotateCcw className="w-4 h-4" />
              </button>
            </div>
          </Card>

          {/* Radar */}
          <Card>
            <CardHead title={t("banking.scenRadarTitle")} subtitle={t("banking.scenRadarSubtitle")} />
            <RadarChart
              data={base.sub_components}
              comparisonData={sim?.sub_components}
              comparisonLabel={t("banking.scenSimulated")}
            />
          </Card>

          {/* Gauges */}
          <Card className="space-y-5">
            <div className="text-center">
              <p className="text-xs text-muted mb-2">{t("banking.scenBase")}</p>
              <div className="flex flex-col items-center">
                <ScoreGauge score={base.overall_score} size={120} />
                <div className="mt-2"><RatingBadge tier={base.rating_tier} size="md" /></div>
              </div>
            </div>
            {sim && (
              <div className="border-t border-line pt-5 text-center">
                <p className="text-xs text-muted mb-2">{t("banking.scenSimulated")}</p>
                <div className="flex flex-col items-center">
                  <ScoreGauge score={sim.overall_score} size={120} />
                  <div className="mt-2"><RatingBadge tier={sim.rating_tier} size="md" /></div>
                </div>
                <div className="mt-3">
                  <Delta value={sim.overall_score - base.overall_score} />
                </div>
              </div>
            )}
          </Card>

          {sim && (
            <div className="lg:col-span-3">
              <AiInsightCard
                title={t("banking.scenInsightTitle")}
                subtitle={t("banking.scenInsightSubtitle", { score: sim.overall_score.toFixed(1), tier: sim.rating_tier })}
                icon={Zap}
                depsKey={`${JSON.stringify(sim.sub_components)}|${sim.overall_score}`}
                fetcher={() => getScenarioInsight(
                  sim.sub_components,
                  base.entity_type ?? undefined,
                  { sub_components: base.sub_components, overall_score: base.overall_score },
                )}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

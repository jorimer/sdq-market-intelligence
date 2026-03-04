import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Sliders, RotateCcw, Zap } from "lucide-react";
import client from "@/shared/api/client";
import { BankSelector } from "../components/BankSelector";
import { RadarChart } from "../components/RadarChart";
import { ScoreGauge } from "../components/ScoreGauge";
import { RatingBadge } from "../components/RatingBadge";
import type { ScoringResult, SubComponents, ScenarioInput } from "@/types";

const SUB_KEYS: (keyof SubComponents)[] = [
  "solidez",
  "calidad",
  "eficiencia",
  "liquidez",
  "diversificacion",
];

const PRESETS: Record<string, ScenarioInput> = {
  optimistic: { solidez: 90, calidad: 85, eficiencia: 80, liquidez: 85, diversificacion: 80 },
  pessimistic: { solidez: 40, calidad: 35, eficiencia: 30, liquidez: 35, diversificacion: 30 },
  baseline: { solidez: 65, calidad: 60, eficiencia: 55, liquidez: 60, diversificacion: 55 },
  stressTest: { solidez: 25, calidad: 20, eficiencia: 15, liquidez: 20, diversificacion: 15 },
};

export function ScenariosPage() {
  const { t } = useTranslation();
  const [bank, setBank] = useState("");
  const [period, setPeriod] = useState("");
  const [baseResult, setBaseResult] = useState<ScoringResult | null>(null);
  const [simResult, setSimResult] = useState<ScoringResult | null>(null);
  const [sliders, setSliders] = useState<ScenarioInput>({ ...PRESETS.baseline });
  const [loading, setLoading] = useState(false);
  const [simulating, setSimulating] = useState(false);

  const loadBaseline = async () => {
    if (!bank) return;
    setLoading(true);
    try {
      const params: Record<string, string> = { bank_name: bank };
      if (period) params.period = period;
      const { data } = await client.post<ScoringResult>(
        "/banking-score/scoring/run",
        null,
        { params }
      );
      setBaseResult(data);
      setSliders({
        solidez: data.sub_components.solidez,
        calidad: data.sub_components.calidad,
        eficiencia: data.sub_components.eficiencia,
        liquidez: data.sub_components.liquidez,
        diversificacion: data.sub_components.diversificacion,
      });
      setSimResult(null);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  };

  const simulate = async () => {
    if (!bank) return;
    setSimulating(true);
    try {
      const { data } = await client.post<ScoringResult>(
        `/banking-score/scoring/${bank}/simulate`,
        { modified_scores: sliders }
      );
      setSimResult(data);
    } catch {
      // silent
    } finally {
      setSimulating(false);
    }
  };

  const updateSlider = (key: keyof ScenarioInput, val: number) => {
    setSliders((prev) => ({ ...prev, [key]: val }));
  };

  const applyPreset = (name: string) => {
    setSliders({ ...PRESETS[name] });
  };

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-gray-900">{t("scenarios.title")}</h2>

      {/* Bank selector + load baseline */}
      <div className="card">
        <div className="flex flex-wrap items-end gap-4">
          <div className="w-64">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t("scoring.selectBank")}
            </label>
            <BankSelector value={bank} onChange={setBank} />
          </div>
          <div className="w-40">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t("rankings.period")}
            </label>
            <input
              type="text"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="2024-Q4"
              className="input-field"
            />
          </div>
          <button
            onClick={loadBaseline}
            disabled={!bank || loading}
            className="btn-primary flex items-center gap-2"
          >
            <Sliders className="w-4 h-4" />
            {loading ? t("scoring.running") : "Cargar Base"}
          </button>
        </div>
      </div>

      {baseResult && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Sliders panel */}
          <div className="card space-y-5">
            <h3 className="font-semibold text-gray-900">{t("scenarios.adjustSliders")}</h3>

            {SUB_KEYS.map((key) => (
              <div key={key}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-gray-600">{t(`sub.${key}`, key)}</span>
                  <span className="font-semibold">{sliders[key].toFixed(1)}</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={0.5}
                  value={sliders[key]}
                  onChange={(e) => updateSlider(key, parseFloat(e.target.value))}
                  className="w-full accent-primary"
                />
              </div>
            ))}

            {/* Presets */}
            <div>
              <p className="text-xs font-medium text-gray-500 mb-2">{t("scenarios.presets")}</p>
              <div className="grid grid-cols-2 gap-2">
                {(["optimistic", "pessimistic", "baseline", "stressTest"] as const).map((p) => (
                  <button
                    key={p}
                    onClick={() => applyPreset(p)}
                    className="text-xs px-2 py-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-700"
                  >
                    {t(`scenarios.${p}`)}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex gap-2">
              <button
                onClick={simulate}
                disabled={simulating}
                className="btn-primary flex-1 flex items-center justify-center gap-2"
              >
                <Zap className="w-4 h-4" />
                {simulating ? "Simulando..." : "Simular"}
              </button>
              <button
                onClick={() => {
                  if (baseResult) {
                    setSliders({
                      solidez: baseResult.sub_components.solidez,
                      calidad: baseResult.sub_components.calidad,
                      eficiencia: baseResult.sub_components.eficiencia,
                      liquidez: baseResult.sub_components.liquidez,
                      diversificacion: baseResult.sub_components.diversificacion,
                    });
                    setSimResult(null);
                  }
                }}
                className="px-3 py-2 rounded-lg border border-gray-200 hover:bg-gray-50"
                title={t("scenarios.reset")}
              >
                <RotateCcw className="w-4 h-4 text-gray-500" />
              </button>
            </div>
          </div>

          {/* Radar chart: current vs simulated */}
          <div className="card">
            <h3 className="font-semibold text-gray-900 mb-4">
              {t("scenarios.currentVsSimulated")}
            </h3>
            <RadarChart
              data={baseResult.sub_components}
              comparisonData={simResult ? simResult.sub_components : undefined}
            />
          </div>

          {/* Score gauges */}
          <div className="card space-y-6">
            <div>
              <p className="text-sm text-gray-500 mb-2">{t("scenarios.baseline")}</p>
              <div className="flex flex-col items-center">
                <ScoreGauge score={baseResult.overall_score} size={120} />
                <div className="mt-2">
                  <RatingBadge tier={baseResult.rating_tier} size="md" />
                </div>
              </div>
            </div>

            {simResult && (
              <div className="border-t border-gray-100 pt-5">
                <p className="text-sm text-gray-500 mb-2">{t("scenarios.simulatedScore")}</p>
                <div className="flex flex-col items-center">
                  <ScoreGauge score={simResult.overall_score} size={120} />
                  <div className="mt-2">
                    <RatingBadge tier={simResult.rating_tier} size="md" />
                  </div>
                </div>

                {/* Delta */}
                <div className="mt-4 text-center">
                  <span className={`text-lg font-bold ${
                    simResult.overall_score > baseResult.overall_score
                      ? "text-success"
                      : simResult.overall_score < baseResult.overall_score
                        ? "text-danger"
                        : "text-gray-500"
                  }`}>
                    {simResult.overall_score > baseResult.overall_score ? "+" : ""}
                    {(simResult.overall_score - baseResult.overall_score).toFixed(1)}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {!baseResult && !loading && (
        <div className="card text-center py-12 text-gray-400">
          <Sliders className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p>Seleccione un banco y cargue la base para iniciar la simulacion.</p>
        </div>
      )}
    </div>
  );
}

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Calculator } from "lucide-react";
import client from "@/shared/api/client";
import { BankSelector } from "../components/BankSelector";
import { RadarChart } from "../components/RadarChart";
import { ScoreGauge } from "../components/ScoreGauge";
import { RatingBadge } from "../components/RatingBadge";
import { IndicatorTable } from "../components/IndicatorTable";
import type { ScoringResult } from "@/types";

export function ScoringPage() {
  const { t } = useTranslation();
  const [bank, setBank] = useState("");
  const [period, setPeriod] = useState("");
  const [result, setResult] = useState<ScoringResult | null>(null);
  const [loading, setLoading] = useState(false);

  const runScoring = async () => {
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
      setResult(data);
    } catch (err) {
      console.error("Scoring failed:", err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-gray-900">{t("scoring.title")}</h2>

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
            onClick={runScoring}
            disabled={!bank || loading}
            className="btn-primary flex items-center gap-2"
          >
            <Calculator className="w-4 h-4" />
            {loading ? t("scoring.running") : t("scoring.runScoring")}
          </button>
        </div>
      </div>

      {!result && !loading && (
        <div className="card text-center py-12 text-gray-400">
          <Calculator className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p>{t("scoring.noResults")}</p>
        </div>
      )}

      {result && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="card flex flex-col items-center">
            <div className="relative">
              <ScoreGauge score={result.overall_score} size={160} />
            </div>
            <p className="text-sm text-gray-500 mt-2">{t("scoring.overallScore")}</p>
            <div className="mt-2">
              <RatingBadge tier={result.rating_tier} size="lg" />
            </div>
          </div>

          <div className="card">
            <h3 className="font-semibold text-gray-900 mb-4">
              {t("scoring.subComponents")}
            </h3>
            <RadarChart data={result.sub_components} />
          </div>

          <div className="card lg:col-span-1">
            <h3 className="font-semibold text-gray-900 mb-4">
              {t("scoring.subComponents")}
            </h3>
            <div className="space-y-3">
              {Object.entries(result.sub_components).map(([key, val]) => (
                <div key={key} className="flex items-center justify-between">
                  <span className="text-sm text-gray-600">
                    {t(`sub.${key}`, key)}
                  </span>
                  <div className="flex items-center gap-2">
                    <div className="w-24 h-2 bg-gray-200 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-primary-light rounded-full transition-all"
                        style={{ width: `${val}%` }}
                      />
                    </div>
                    <span className="text-sm font-semibold w-10 text-right">
                      {val.toFixed(1)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="card lg:col-span-3">
            <h3 className="font-semibold text-gray-900 mb-4">
              {t("scoring.indicators")}
            </h3>
            <IndicatorTable indicators={result.indicators} />
          </div>
        </div>
      )}
    </div>
  );
}

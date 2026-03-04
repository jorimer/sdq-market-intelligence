import { useState } from "react";
import { useTranslation } from "react-i18next";
import { GitCompare, Plus, X } from "lucide-react";
import client from "@/shared/api/client";
import { BankSelector } from "../components/BankSelector";
import { RadarChart } from "../components/RadarChart";
import { PeerBar } from "../components/PeerBar";
import { RatingBadge } from "../components/RatingBadge";
import { ScoreGauge } from "../components/ScoreGauge";
import type { ScoringResult, ComparisonBank } from "@/types";

const MAX_BANKS = 4;

export function ComparePage() {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<string[]>([""]);
  const [period, setPeriod] = useState("");
  const [results, setResults] = useState<ComparisonBank[]>([]);
  const [loading, setLoading] = useState(false);

  const addBank = () => {
    if (selected.length < MAX_BANKS) {
      setSelected([...selected, ""]);
    }
  };

  const removeBank = (idx: number) => {
    setSelected(selected.filter((_, i) => i !== idx));
  };

  const setBank = (idx: number, val: string) => {
    const copy = [...selected];
    copy[idx] = val;
    setSelected(copy);
  };

  const validBanks = selected.filter((b) => b.trim() !== "");

  const runComparison = async () => {
    if (validBanks.length < 2) return;
    setLoading(true);
    try {
      const promises = validBanks.map((bank) => {
        const params: Record<string, string> = { bank_name: bank };
        if (period) params.period = period;
        return client.post<ScoringResult>("/banking-score/scoring/run", null, { params });
      });
      const responses = await Promise.all(promises);
      setResults(
        responses.map((r, i) => ({
          bank_name: validBanks[i],
          scoring_result: r.data,
        }))
      );
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  };

  // Prepare bar chart data from results
  const barData = results.map((r) => ({
    bank_name: r.bank_name,
    score: r.scoring_result.overall_score,
  }));

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-gray-900">{t("compare.title")}</h2>

      {/* Selection panel */}
      <div className="card space-y-4">
        <p className="text-sm text-gray-500">{t("compare.selectBanks")}</p>

        <div className="space-y-3">
          {selected.map((bank, idx) => (
            <div key={idx} className="flex items-center gap-3">
              <div className="w-64">
                <BankSelector value={bank} onChange={(v) => setBank(idx, v)} />
              </div>
              {selected.length > 1 && (
                <button
                  onClick={() => removeBank(idx)}
                  className="text-gray-400 hover:text-danger"
                  title={t("compare.remove")}
                >
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>
          ))}
        </div>

        <div className="flex flex-wrap items-end gap-4">
          {selected.length < MAX_BANKS && (
            <button
              onClick={addBank}
              className="text-sm text-primary hover:underline flex items-center gap-1"
            >
              <Plus className="w-3.5 h-3.5" />
              {t("compare.addBank")}
            </button>
          )}

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
            onClick={runComparison}
            disabled={validBanks.length < 2 || loading}
            className="btn-primary flex items-center gap-2"
          >
            <GitCompare className="w-4 h-4" />
            {loading ? t("compare.comparing") : t("compare.runComparison")}
          </button>
        </div>
      </div>

      {/* Results */}
      {results.length === 0 && !loading && (
        <div className="card text-center py-12 text-gray-400">
          <GitCompare className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p>{t("compare.noSelection")}</p>
        </div>
      )}

      {results.length > 0 && (
        <>
          {/* Score gauges row */}
          <div className={`grid gap-4 ${
            results.length === 2 ? "grid-cols-2" :
            results.length === 3 ? "grid-cols-3" : "grid-cols-4"
          }`}>
            {results.map((r) => (
              <div key={r.bank_name} className="card flex flex-col items-center">
                <p className="text-sm font-medium text-gray-700 mb-2">{r.bank_name}</p>
                <ScoreGauge score={r.scoring_result.overall_score} size={100} />
                <div className="mt-2">
                  <RatingBadge tier={r.scoring_result.rating_tier} size="sm" />
                </div>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Overall score bar comparison */}
            <div className="card">
              <h3 className="font-semibold text-gray-900 mb-4">Score General</h3>
              <PeerBar data={barData} highlightBank={results[0]?.bank_name} />
            </div>

            {/* Radar overlay — first two banks */}
            <div className="card">
              <h3 className="font-semibold text-gray-900 mb-4">Sub-componentes</h3>
              <RadarChart
                data={results[0].scoring_result.sub_components}
                comparisonData={results.length > 1 ? results[1].scoring_result.sub_components : undefined}
              />
              {results.length > 1 && (
                <div className="flex items-center justify-center gap-6 mt-3 text-xs text-gray-500">
                  <div className="flex items-center gap-1.5">
                    <div className="w-3 h-3 rounded-full bg-primary" />
                    {results[0].bank_name}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <div className="w-3 h-3 rounded-full bg-danger" />
                    {results[1].bank_name}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Sub-component comparison table */}
          <div className="card">
            <h3 className="font-semibold text-gray-900 mb-4">Detalle por Sub-componente</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className="text-left py-2 px-3 font-medium text-gray-500">Sub-componente</th>
                    {results.map((r) => (
                      <th key={r.bank_name} className="text-right py-2 px-3 font-medium text-gray-500">
                        {r.bank_name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(["solidez", "calidad", "eficiencia", "liquidez", "diversificacion"] as const).map(
                    (key) => (
                      <tr key={key} className="border-b border-gray-100">
                        <td className="py-2 px-3 text-gray-600">{t(`sub.${key}`, key)}</td>
                        {results.map((r) => {
                          const val = r.scoring_result.sub_components[key];
                          return (
                            <td key={r.bank_name} className="py-2 px-3 text-right font-semibold">
                              <span className={
                                val >= 70 ? "text-success" :
                                val >= 50 ? "text-primary" :
                                "text-danger"
                              }>
                                {val.toFixed(1)}
                              </span>
                            </td>
                          );
                        })}
                      </tr>
                    )
                  )}
                  <tr className="border-t-2 border-gray-200">
                    <td className="py-2 px-3 font-semibold text-gray-900">Score General</td>
                    {results.map((r) => (
                      <td key={r.bank_name} className="py-2 px-3 text-right font-bold text-gray-900">
                        {r.scoring_result.overall_score.toFixed(1)}
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

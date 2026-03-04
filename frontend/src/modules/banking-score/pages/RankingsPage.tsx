import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Trophy, ArrowUp, ArrowDown, Minus } from "lucide-react";
import client from "@/shared/api/client";
import { RatingBadge } from "../components/RatingBadge";
import { LoadingSkeleton } from "@/shared/components/LoadingSkeleton";
import type { RankingEntry } from "@/types";

export function RankingsPage() {
  const { t } = useTranslation();
  const [rankings, setRankings] = useState<RankingEntry[]>([]);
  const [period, setPeriod] = useState("");
  const [periods, setPeriods] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    client
      .get("/banking-score/data/stats")
      .then((r) => {
        const p = r.data.periods ?? [];
        setPeriods(p);
        if (p.length > 0) setPeriod(p[p.length - 1]);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!period) return;
    setLoading(true);
    client
      .get<RankingEntry[]>("/banking-score/scoring/rankings", {
        params: { period },
      })
      .then((r) => setRankings(r.data))
      .catch(() => setRankings([]))
      .finally(() => setLoading(false));
  }, [period]);

  const ChangeIcon = ({ change }: { change: number }) => {
    if (change > 0) return <ArrowUp className="w-3.5 h-3.5 text-success" />;
    if (change < 0) return <ArrowDown className="w-3.5 h-3.5 text-danger" />;
    return <Minus className="w-3.5 h-3.5 text-gray-400" />;
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-gray-900">{t("rankings.title")}</h2>
        <select
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
          className="input-field w-40"
        >
          {periods.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      </div>

      <div className="card">
        {loading ? (
          <LoadingSkeleton rows={8} />
        ) : rankings.length === 0 ? (
          <div className="text-center py-12 text-gray-400">
            <Trophy className="w-12 h-12 mx-auto mb-3 opacity-30" />
            <p>{t("rankings.noData")}</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-3 px-3 font-medium text-gray-500">{t("rankings.rank")}</th>
                  <th className="text-left py-3 px-3 font-medium text-gray-500">{t("rankings.bank")}</th>
                  <th className="text-right py-3 px-3 font-medium text-gray-500">{t("rankings.score")}</th>
                  <th className="text-center py-3 px-3 font-medium text-gray-500">{t("rankings.tier")}</th>
                  <th className="text-center py-3 px-3 font-medium text-gray-500">{t("rankings.change")}</th>
                </tr>
              </thead>
              <tbody>
                {rankings.map((r) => (
                  <tr key={r.bank_name} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="py-3 px-3 font-bold text-gray-400">#{r.rank}</td>
                    <td className="py-3 px-3 font-medium text-gray-900">{r.bank_name}</td>
                    <td className="py-3 px-3 text-right font-semibold">{r.overall_score.toFixed(1)}</td>
                    <td className="py-3 px-3 text-center">
                      <RatingBadge tier={r.rating_tier} size="sm" />
                    </td>
                    <td className="py-3 px-3 text-center">
                      <div className="inline-flex items-center gap-1">
                        <ChangeIcon change={r.change} />
                        {r.change !== 0 && (
                          <span className={`text-xs font-medium ${r.change > 0 ? "text-success" : "text-danger"}`}>
                            {Math.abs(r.change)}
                          </span>
                        )}
                      </div>
                    </td>
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

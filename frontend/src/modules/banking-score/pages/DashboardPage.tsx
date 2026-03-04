import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Building2, TrendingUp, Calendar, Database } from "lucide-react";
import client from "@/shared/api/client";
import { RatingBadge } from "../components/RatingBadge";
import { CardSkeleton } from "@/shared/components/LoadingSkeleton";
import type { DataStats, RankingEntry, RatingAction } from "@/types";

export function DashboardPage() {
  const { t } = useTranslation();
  const [stats, setStats] = useState<DataStats | null>(null);
  const [topBanks, setTopBanks] = useState<RankingEntry[]>([]);
  const [actions, setActions] = useState<RatingAction[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      client.get<DataStats>("/banking-score/data/stats"),
      client.get<RankingEntry[]>("/banking-score/scoring/rankings"),
      client.get<RatingAction[]>("/banking-score/scoring/actions"),
    ])
      .then(([statsR, rankR, actR]) => {
        setStats(statsR.data);
        setTopBanks(rankR.data.slice(0, 5));
        setActions(actR.data.slice(0, 5));
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="space-y-6">
        <h2 className="text-xl font-bold text-gray-900">{t("dashboard.title")}</h2>
        <div className="grid grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => <CardSkeleton key={i} />)}
        </div>
      </div>
    );
  }

  const statCards = [
    { icon: Building2, label: t("dashboard.totalBanks"), value: stats?.total_banks ?? 0 },
    { icon: TrendingUp, label: t("dashboard.avgScore"), value: topBanks.length ? (topBanks.reduce((s, b) => s + b.overall_score, 0) / topBanks.length).toFixed(1) : "—" },
    { icon: Calendar, label: t("dashboard.latestPeriod"), value: stats?.latest_period ?? "—" },
    { icon: Database, label: t("dashboard.totalRecords"), value: stats?.total_records ?? 0 },
  ];

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-gray-900">{t("dashboard.title")}</h2>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map(({ icon: Icon, label, value }) => (
          <div key={label} className="card flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
              <Icon className="w-5 h-5 text-primary" />
            </div>
            <div>
              <p className="text-sm text-gray-500">{label}</p>
              <p className="text-xl font-bold text-gray-900">{value}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card">
          <h3 className="font-semibold text-gray-900 mb-4">{t("dashboard.topBanks")}</h3>
          {topBanks.length === 0 ? (
            <p className="text-gray-400 text-sm">{t("common.noData")}</p>
          ) : (
            <div className="space-y-3">
              {topBanks.map((bank, i) => (
                <div key={bank.bank_name} className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="w-6 text-sm font-bold text-gray-400">#{i + 1}</span>
                    <span className="text-sm font-medium text-gray-700">{bank.bank_name}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-semibold">{bank.overall_score.toFixed(1)}</span>
                    <RatingBadge tier={bank.rating_tier} size="sm" />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <h3 className="font-semibold text-gray-900 mb-4">{t("dashboard.recentActions")}</h3>
          {actions.length === 0 ? (
            <p className="text-gray-400 text-sm">{t("common.noData")}</p>
          ) : (
            <div className="space-y-3">
              {actions.map((a) => (
                <div key={a.id} className="flex items-center justify-between text-sm">
                  <div>
                    <span className="font-medium text-gray-700">{a.bank_name}</span>
                    <span className="text-gray-400 ml-2">{a.period}</span>
                  </div>
                  <RatingBadge tier={a.rating_tier} size="sm" />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

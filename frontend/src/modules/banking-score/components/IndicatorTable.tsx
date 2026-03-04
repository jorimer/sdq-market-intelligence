import { useTranslation } from "react-i18next";
import type { IndicatorDetail } from "@/types";

interface Props {
  indicators: Record<string, IndicatorDetail>;
}

function getScoreColor(score: number): string {
  if (score >= 85) return "text-success";
  if (score >= 70) return "text-primary-light";
  if (score >= 55) return "text-warning";
  return "text-danger";
}

function getScoreBg(score: number): string {
  if (score >= 85) return "bg-success/10";
  if (score >= 70) return "bg-primary-light/10";
  if (score >= 55) return "bg-warning/10";
  return "bg-danger/10";
}

export function IndicatorTable({ indicators }: Props) {
  const { t } = useTranslation();

  const entries = Object.entries(indicators);

  if (entries.length === 0) {
    return <p className="text-gray-500 text-sm">{t("common.noData")}</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200">
            <th className="text-left py-2 px-3 font-medium text-gray-500">
              Indicador
            </th>
            <th className="text-right py-2 px-3 font-medium text-gray-500">
              Valor
            </th>
            <th className="text-right py-2 px-3 font-medium text-gray-500">
              Score
            </th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([key, detail]) => (
            <tr key={key} className="border-b border-gray-100 hover:bg-gray-50">
              <td className="py-2 px-3 text-gray-700">
                {t(`indicators.${key}`, key)}
              </td>
              <td className="py-2 px-3 text-right text-gray-600">
                {typeof detail.raw === "number" ? detail.raw.toFixed(2) : "—"}
              </td>
              <td className="py-2 px-3 text-right">
                <span
                  className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${getScoreColor(
                    detail.score
                  )} ${getScoreBg(detail.score)}`}
                >
                  {detail.score.toFixed(1)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

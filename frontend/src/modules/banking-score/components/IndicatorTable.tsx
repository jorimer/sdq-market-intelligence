import { useTranslation } from "react-i18next";
import type { IndicatorDetail } from "@/types";

interface Props {
  indicators: Record<string, IndicatorDetail>;
}

function getScoreColor(score: number): string {
  if (score >= 85) return "text-ok";
  if (score >= 70) return "text-accent";
  if (score >= 55) return "text-warn";
  return "text-alert";
}

function getScoreBg(score: number): string {
  if (score >= 85) return "bg-ok-soft";
  if (score >= 70) return "bg-accent-soft";
  if (score >= 55) return "bg-warn-soft";
  return "bg-alert-soft";
}

export function IndicatorTable({ indicators }: Props) {
  const { t } = useTranslation();

  const entries = Object.entries(indicators);

  if (entries.length === 0) {
    return <p className="text-muted text-sm">{t("common.noData")}</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line">
            <th className="text-left py-2 px-3 font-medium text-muted">
              Indicador
            </th>
            <th className="text-right py-2 px-3 font-medium text-muted">
              Valor
            </th>
            <th className="text-right py-2 px-3 font-medium text-muted">
              Score
            </th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([key, detail]) => (
            <tr key={key} className="border-b border-line hover:bg-surface2">
              <td className="py-2 px-3 text-body">
                {t(`indicators.${key}`, key)}
              </td>
              <td className="py-2 px-3 text-right text-body">
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

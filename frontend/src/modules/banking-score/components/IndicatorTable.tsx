import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { IndicatorDetail } from "@/types";
import { IndicatorDetailDrawer } from "./IndicatorDetailDrawer";

interface Props {
  indicators: Record<string, IndicatorDetail>;
  /** When provided, rows become clickable and open the drill-down drawer. */
  bankId?: string;
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

export function IndicatorTable({ indicators, bankId }: Props) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<string | null>(null);

  const entries = Object.entries(indicators);
  const clickable = Boolean(bankId);

  if (entries.length === 0) {
    return <p className="text-muted text-sm">{t("common.noData")}</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line">
            <th className="text-left py-2 px-3 font-medium text-muted">Indicador</th>
            <th className="text-right py-2 px-3 font-medium text-muted">Valor</th>
            <th className="text-right py-2 px-3 font-medium text-muted">Score</th>
            {clickable && <th className="w-8" />}
          </tr>
        </thead>
        <tbody>
          {entries.map(([key, detail]) => (
            <tr
              key={key}
              className={`border-b border-line ${clickable ? "cursor-pointer hover:bg-surface2" : ""}`}
              onClick={clickable ? () => setSelected(key) : undefined}
              tabIndex={clickable ? 0 : undefined}
              onKeyDown={clickable ? (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setSelected(key)) : undefined}
            >
              <td className="py-2 px-3 text-body">{t(`indicators.${key}`, key)}</td>
              {/* Un indicador que el motor declaró NO disponible no tiene valor ni score que
                  mostrar: su `raw` es el 0.0 por defecto de la estructura y su score, el que
                  esa curva le da al cero — para los inversos, 100. Publicarlo tal cual decía
                  «cero concentración, perfecto» cuando lo que pasa es que el insumo no vino.
                  La fila se LISTA igual: esconderla se lee como que el indicador no existe. */}
              {detail.available === false ? (
                <>
                  <td className="py-2 px-3 text-right text-faint mono tabular-nums">s/d</td>
                  <td className="py-2 px-3 text-right text-faint">—</td>
                </>
              ) : (
                <>
                  <td className="py-2 px-3 text-right text-body mono tabular-nums">
                    {typeof detail.raw === "number" ? detail.raw.toFixed(2) : "—"}
                  </td>
                  <td className="py-2 px-3 text-right">
                    <span
                      className={`inline-block px-2 py-0.5 rounded text-xs font-semibold tabular-nums ${getScoreColor(detail.score)} ${getScoreBg(detail.score)}`}
                    >
                      {detail.score.toFixed(1)}
                    </span>
                  </td>
                </>
              )}
              {clickable && (
                <td className="py-2 pr-3 text-right">
                  <ChevronRight className="w-4 h-4 text-faint inline-block" />
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>

      {clickable && selected && (
        <IndicatorDetailDrawer bankId={bankId!} indicatorKey={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

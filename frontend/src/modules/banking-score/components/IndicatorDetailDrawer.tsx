import { useEffect, useState } from "react";
import { X, Sparkles, TrendingUp, Users } from "lucide-react";
import { TrendChart } from "./TrendChart";
import { StateBlock, Skeleton } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { getIndicatorDetail, type IndicatorDetail } from "../api";

interface Props {
  bankId: string;
  indicatorKey: string;
  onClose: () => void;
}

function scoreColor(score: number): string {
  if (score >= 85) return "text-ok bg-ok-soft";
  if (score >= 70) return "text-accent bg-accent-soft";
  if (score >= 55) return "text-warn bg-warn-soft";
  return "text-alert bg-alert-soft";
}

const DIRECTION_HINT: Record<string, string> = {
  higher: "Mayor es mejor",
  lower: "Menor es mejor",
  target: "Óptimo en un rango intermedio",
};

function fmtRaw(raw: number | null, unit: string): string {
  if (raw === null || raw === undefined) return "—";
  if (unit === "índice") return fmtNum(raw, 0);
  return `${fmtNum(raw, 2)}%`;
}

function PeerRow({ label, stats, score }: { label: string; stats: { n: number; median_score: number; percentile: number } | null; score: number }) {
  if (!stats) return null;
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-sm text-body truncate min-w-0 flex-1">{label}</span>
        <span className="text-xs text-muted shrink-0 ml-2">
          n={stats.n} · mediana <span className="mono text-body">{fmtNum(stats.median_score, 0)}</span>
        </span>
      </div>
      {/* score track with median tick + this entity marker */}
      <div className="relative h-2 rounded-full bg-surface2 overflow-hidden">
        <div className="absolute inset-y-0 left-0 rounded-full bg-accent" style={{ width: `${Math.max(0, Math.min(100, score))}%` }} />
        <div className="absolute inset-y-0 w-px bg-linestrong" style={{ left: `${Math.max(0, Math.min(100, stats.median_score))}%` }} />
      </div>
      <div className="text-xs text-muted mt-1">
        Percentil <span className="mono text-body">{fmtNum(stats.percentile, 0)}</span> del grupo
      </div>
    </div>
  );
}

export function IndicatorDetailDrawer({ bankId, indicatorKey, onClose }: Props) {
  const [detail, setDetail] = useState<IndicatorDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    getIndicatorDetail(bankId, indicatorKey)
      .then((d) => active && setDetail(d))
      .catch(() => active && setError(true))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [bankId, indicatorKey]);

  const ai = detail?.ai_insight;
  const aiUnavailable = !ai || ai.model_used === "static_fallback";

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* overlay */}
      <button
        aria-label="Cerrar"
        onClick={onClose}
        className="absolute inset-0 bg-ink/40 backdrop-blur-sm"
      />
      {/* panel */}
      <div className="relative w-full max-w-lg h-full bg-surface border-l border-line shadow-pop overflow-y-auto">
        <div className="sticky top-0 z-10 bg-surface border-b border-line px-5 py-4 flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-xs text-muted truncate">
              {detail?.bank_name ?? "Indicador"}
            </div>
            <h2 className="text-base font-semibold text-ink font-display truncate">
              {detail?.label ?? "Detalle del indicador"}
            </h2>
          </div>
          <button onClick={onClose} className="btn btn-ghost shrink-0 -mr-2" aria-label="Cerrar">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-6">
          {loading ? (
            <div className="space-y-3">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-40 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
          ) : error || !detail ? (
            <StateBlock kind="error" message="No se pudo cargar el detalle del indicador." />
          ) : (
            <>
              {/* value + score */}
              <div className="flex items-end justify-between gap-4">
                <div className="min-w-0">
                  <div className="text-xs text-muted mb-1">
                    {detail.sub_component} · {DIRECTION_HINT[detail.direction] ?? ""}
                  </div>
                  <div className="text-3xl font-semibold text-ink mono tabular-nums">
                    {fmtRaw(detail.latest.raw, detail.unit)}
                  </div>
                  <div className="text-xs text-muted mt-1 mono">{detail.latest.period_end}</div>
                </div>
                {detail.latest.available && (
                  <div className="shrink-0 text-right">
                    <span className={`inline-block px-2.5 py-1 rounded text-sm font-semibold ${scoreColor(detail.latest.score)}`}>
                      {fmtNum(detail.latest.score, 1)}
                    </span>
                    {detail.latest.band && (
                      <div className="text-xs text-muted mt-1 capitalize">{detail.latest.band}</div>
                    )}
                  </div>
                )}
              </div>

              <p className="text-sm text-body leading-relaxed">{detail.interpretation}</p>

              {/* trend */}
              {detail.trend.length > 1 && (
                <section>
                  <div className="flex items-center gap-2 mb-2 text-sm font-medium text-ink">
                    <TrendingUp className="w-4 h-4 text-muted" /> Tendencia (score)
                  </div>
                  <TrendChart data={detail.trend.map((t) => ({ period: t.period_end, score: t.score }))} />
                </section>
              )}

              {/* peers */}
              {detail.peers && (detail.peers.sector || detail.peers.entity_type) && (
                <section>
                  <div className="flex items-center gap-2 mb-3 text-sm font-medium text-ink">
                    <Users className="w-4 h-4 text-muted" /> Posición vs pares
                  </div>
                  <div className="space-y-4">
                    <PeerRow label="Todo el sector" stats={detail.peers.sector} score={detail.latest.score} />
                    <PeerRow
                      label={`Mismo tipo (${detail.peers.entity_type_label ?? "—"})`}
                      stats={detail.peers.entity_type}
                      score={detail.latest.score}
                    />
                  </div>
                </section>
              )}

              {/* AI insight */}
              <section>
                <div className="flex items-center gap-2 mb-2 text-sm font-medium text-ink">
                  <Sparkles className="w-4 h-4 text-accent" /> Insight de IA
                </div>
                {aiUnavailable ? (
                  <p className="text-sm text-muted leading-relaxed">
                    El análisis de IA no está disponible (clave de Anthropic no configurada o
                    sin dato para el período). El detalle numérico de arriba es completo.
                  </p>
                ) : (
                  <div className="text-sm text-body leading-relaxed whitespace-pre-wrap">
                    {ai!.text}
                    <div className="text-xs text-muted mt-3">
                      Generado por IA ({ai!.model_used}){ai!.from_cache ? " · caché" : ""}. Verifica antes de decidir.
                    </div>
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

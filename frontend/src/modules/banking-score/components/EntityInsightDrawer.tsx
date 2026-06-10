import { useEffect, useState } from "react";
import { X, Sparkles, TrendingUp, Users, Layers, ChevronRight } from "lucide-react";
import { TrendChart } from "./TrendChart";
import { RatingBadge } from "./RatingBadge";
import { IndicatorDetailDrawer } from "./IndicatorDetailDrawer";
import { StateBlock, Skeleton } from "@/shared/ui/primitives";
import { Markdown } from "@/shared/ui/Markdown";
import { fmtNum } from "@/shared/lib/format";
import { getEntityInsight, type EntityInsight } from "../api";

interface Props {
  bankId: string;
  onClose: () => void;
}

function scoreColor(score: number): string {
  if (score >= 85) return "text-ok bg-ok-soft";
  if (score >= 70) return "text-accent bg-accent-soft";
  if (score >= 55) return "text-warn bg-warn-soft";
  return "text-alert bg-alert-soft";
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

export function EntityInsightDrawer({ bankId, onClose }: Props) {
  const [detail, setDetail] = useState<EntityInsight | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [indicatorKey, setIndicatorKey] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && (indicatorKey ? setIndicatorKey(null) : onClose());
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, indicatorKey]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    setAiLoading(false);
    getEntityInsight(bankId, false)
      .then((d) => {
        if (!active) return;
        setDetail(d);
        setLoading(false);
        setAiLoading(true);
        getEntityInsight(bankId, true)
          .then((full) => active && setDetail((prev) => (prev ? { ...prev, ai_insight: full.ai_insight } : full)))
          .catch(() => undefined)
          .finally(() => active && setAiLoading(false));
      })
      .catch(() => {
        if (!active) return;
        setError(true);
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [bankId]);

  const ai = detail?.ai_insight;
  const aiUnavailable = !ai || ai.model_used === "static_fallback";

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button aria-label="Cerrar" onClick={onClose} className="absolute inset-0 bg-ink/40 backdrop-blur-sm" />
      <div className="relative w-full max-w-lg h-full bg-surface border-l border-line shadow-pop overflow-y-auto">
        <div className="sticky top-0 z-10 bg-surface border-b border-line px-5 py-4 flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-xs text-muted truncate">Entidad · {detail?.latest.period_end ?? ""}</div>
            <h2 className="text-base font-semibold text-ink font-display truncate">
              {detail?.bank_name ?? "Detalle de la entidad"}
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
            <StateBlock kind="error" message="No se pudo cargar el detalle de la entidad." />
          ) : (
            <>
              <div className="flex items-end justify-between gap-4">
                <div className="min-w-0">
                  <div className="text-3xl font-semibold text-ink mono tabular-nums">
                    {fmtNum(detail.latest.overall_score, 1)}
                  </div>
                  <div className="text-xs text-muted mt-1">Score SDQ global</div>
                </div>
                <RatingBadge tier={detail.latest.rating_tier} size="lg" />
              </div>

              {/* sub-components with driver/drag */}
              <section>
                <div className="flex items-center gap-2 mb-3 text-sm font-medium text-ink">
                  <Layers className="w-4 h-4 text-muted" /> Sub-componentes
                </div>
                <div className="space-y-4">
                  {detail.sub_components.map((s) => (
                    <div key={s.key}>
                      <div className="flex items-baseline justify-between mb-1">
                        <span className="text-sm text-body truncate min-w-0 flex-1">
                          {s.label} <span className="text-xs text-faint">· peso {fmtNum((s.weight ?? 0) * 100, 0)}%</span>
                        </span>
                        <span className="text-sm font-semibold text-ink mono tabular-nums shrink-0 ml-2">
                          {s.score === null ? "N/D" : fmtNum(s.score, 1)}
                        </span>
                      </div>
                      <div className="h-2 rounded-full bg-surface2 overflow-hidden">
                        <div className="h-full rounded-full bg-accent" style={{ width: `${s.score ?? 0}%` }} />
                      </div>
                      {(s.driver || s.drag) && (
                        <div className="flex flex-wrap gap-2 mt-2">
                          {s.driver && (
                            <button onClick={() => setIndicatorKey(s.driver!.key)}
                              className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-ok-soft text-ok hover:opacity-80">
                              ↑ {s.driver.label} <ChevronRight className="w-3 h-3" />
                            </button>
                          )}
                          {s.drag && s.drag.key !== s.driver?.key && (
                            <button onClick={() => setIndicatorKey(s.drag!.key)}
                              className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-alert-soft text-alert hover:opacity-80">
                              ↓ {s.drag.label} <ChevronRight className="w-3 h-3" />
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </section>

              {detail.trend.length > 1 && (
                <section>
                  <div className="flex items-center gap-2 mb-2 text-sm font-medium text-ink">
                    <TrendingUp className="w-4 h-4 text-muted" /> Tendencia (score global)
                  </div>
                  <TrendChart data={detail.trend.map((t) => ({ period: t.period_end, score: t.score }))} />
                </section>
              )}

              {detail.peers && (detail.peers.sector || detail.peers.entity_type) && (
                <section>
                  <div className="flex items-center gap-2 mb-3 text-sm font-medium text-ink">
                    <Users className="w-4 h-4 text-muted" /> Posición vs pares
                  </div>
                  <div className="space-y-4">
                    <PeerRow label="Todo el sector" stats={detail.peers.sector} score={detail.latest.overall_score} />
                    <PeerRow label={`Mismo tipo (${detail.peers.entity_type_label ?? "—"})`} stats={detail.peers.entity_type} score={detail.latest.overall_score} />
                  </div>
                </section>
              )}

              <section>
                <div className="flex items-center gap-2 mb-2 text-sm font-medium text-ink">
                  <Sparkles className="w-4 h-4 text-accent" /> Fundamento del rating (IA)
                </div>
                {aiLoading ? (
                  <div className="space-y-2">
                    <p className="text-xs text-muted">Generando análisis de IA… (~10–15s)</p>
                    <Skeleton className="h-4 w-full" />
                    <Skeleton className="h-4 w-11/12" />
                    <Skeleton className="h-4 w-3/4" />
                  </div>
                ) : aiUnavailable ? (
                  <p className="text-sm text-muted leading-relaxed">
                    El análisis de IA no está disponible (clave de Anthropic no configurada).
                    El detalle de arriba es completo.
                  </p>
                ) : (
                  <div>
                    <Markdown text={ai!.text} />
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

      {/* drill from a sub-component's driver/drag into the indicator drawer */}
      {indicatorKey && (
        <IndicatorDetailDrawer bankId={bankId} indicatorKey={indicatorKey} onClose={() => setIndicatorKey(null)} />
      )}
    </div>
  );
}

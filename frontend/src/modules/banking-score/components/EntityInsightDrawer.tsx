import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Sparkles, TrendingUp, Users, Layers, ChevronRight } from "lucide-react";
import { TrendChart } from "./TrendChart";
import { PerfilCompacto } from "./PerfilSDQ";
import { IndicatorDetailDrawer } from "./IndicatorDetailDrawer";
import { entityTypeLabel } from "../entityTypes";
import { StateBlock, Skeleton } from "@/shared/ui/primitives";
import { InsightDrawerShell } from "@/shared/ui/InsightDrawerShell";
import { AiInsightBody } from "@/shared/ui/AiInsightBody";
import { DeepToggle } from "@/shared/ui/DeepToggle";
import { DownloadInsightButton } from "@/shared/ui/DownloadInsightButton";
import { useTwoPhaseInsight } from "@/shared/ui/useTwoPhaseInsight";
import { fmtNum } from "@/shared/lib/format";
import { getEntityInsight, type EntityInsight } from "../api";
import { useAudience } from "../audience";
import { AudienceSelector } from "./AudienceSelector";

interface Props {
  bankId: string;
  onClose: () => void;
}

function PeerRow({ label, stats, score }: { label: string; stats: { n: number; median_score: number; percentile: number } | null; score: number }) {
  const { t } = useTranslation();
  if (!stats) return null;
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-sm text-body truncate min-w-0 flex-1">{label}</span>
        <span className="text-xs text-muted shrink-0 ml-2">
          n={stats.n} · {t("banking.peerMedian")} <span className="mono text-body">{fmtNum(stats.median_score, 0)}</span>
        </span>
      </div>
      <div className="relative h-2 rounded-full bg-surface2 overflow-hidden">
        <div className="absolute inset-y-0 left-0 rounded-full bg-accent" style={{ width: `${Math.max(0, Math.min(100, score))}%` }} />
        <div className="absolute inset-y-0 w-px bg-linestrong" style={{ left: `${Math.max(0, Math.min(100, stats.median_score))}%` }} />
      </div>
      <div className="text-xs text-muted mt-1">
        {t("banking.peerPercentilePre")} <span className="mono text-body">{fmtNum(stats.percentile, 0)}</span> {t("banking.peerPercentilePost")}
      </div>
    </div>
  );
}

export function EntityInsightDrawer({ bankId, onClose }: Props) {
  const { t } = useTranslation();
  const [indicatorKey, setIndicatorKey] = useState<string | null>(null);
  const [audience, setAudience] = useAudience();
  const [deep, setDeep] = useState(false);
  const { data: detail, ai, loading, aiLoading, error } = useTwoPhaseInsight<EntityInsight>(
    (withAi) => getEntityInsight(bankId, withAi, audience, deep),
    `${bankId}:${audience}:${deep}`,
    { pickAi: (d) => d.ai_insight },
  );

  return (
    <>
      <InsightDrawerShell
        eyebrow={`${t("banking.entEyebrow")} · ${detail?.latest.period_end ?? ""}`}
        title={detail?.bank_name ?? t("banking.entTitleFallback")}
        onClose={onClose}
        onEscape={() => (indicatorKey ? setIndicatorKey(null) : onClose())}
      >
        {loading ? (
          <div className="space-y-3">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-40 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
        ) : error || !detail ? (
          <StateBlock kind="error" message={t("banking.entError")} />
        ) : (
          <>
            <div className="flex items-end justify-between gap-4">
              <div className="min-w-0">
                <div className="text-3xl font-semibold text-ink mono tabular-nums">
                  {fmtNum(detail.latest.overall_score, 1)}
                </div>
                <div className="text-xs text-muted mt-1">{t("banking.entGlobalScore")}</div>
              </div>
              <PerfilCompacto ejecucion={detail.latest.ejecucion} bandaEjecucion={detail.latest.banda_ejecucion}
                              resiliencia={detail.latest.resiliencia} bandaResiliencia={detail.latest.banda_resiliencia} />
            </div>

            {/* sub-components with driver/drag */}
            <section>
              <div className="flex items-center gap-2 mb-3 text-sm font-medium text-ink">
                <Layers className="w-4 h-4 text-muted" /> {t("banking.entSubComponents")}
              </div>
              <div className="space-y-4">
                {detail.sub_components.map((s) => (
                  <div key={s.key}>
                    <div className="flex items-baseline justify-between mb-1">
                      <span className="text-sm text-body truncate min-w-0 flex-1">
                        {t(`sub.${s.key}`, s.label)} <span className="text-xs text-faint">· {t("banking.entWeight", { n: fmtNum((s.weight ?? 0) * 100, 0) })}</span>
                      </span>
                      <span className="text-sm font-semibold text-ink mono tabular-nums shrink-0 ml-2">
                        {s.score === null ? t("banking.na") : fmtNum(s.score, 1)}
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
                            ↑ {t(`indicators.${s.driver.key}`, s.driver.label)} <ChevronRight className="w-3 h-3" />
                          </button>
                        )}
                        {s.drag && s.drag.key !== s.driver?.key && (
                          <button onClick={() => setIndicatorKey(s.drag!.key)}
                            className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-alert-soft text-alert hover:opacity-80">
                            ↓ {t(`indicators.${s.drag.key}`, s.drag.label)} <ChevronRight className="w-3 h-3" />
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
                  <TrendingUp className="w-4 h-4 text-muted" /> {t("banking.entTrendTitle")}
                </div>
                <TrendChart data={detail.trend.map((pt) => ({ period: pt.period_end, score: pt.score }))} />
              </section>
            )}

            {detail.peers && (detail.peers.sector || detail.peers.entity_type) && (
              <section>
                <div className="flex items-center gap-2 mb-3 text-sm font-medium text-ink">
                  <Users className="w-4 h-4 text-muted" /> {t("banking.peerTitle")}
                </div>
                <div className="space-y-4">
                  <PeerRow label={t("banking.peerSector")} stats={detail.peers.sector} score={detail.latest.overall_score} />
                  <PeerRow label={t("banking.peerSameType", { type: detail.entity_type ? entityTypeLabel(detail.entity_type, t) : (detail.peers.entity_type_label ?? "—") })} stats={detail.peers.entity_type} score={detail.latest.overall_score} />
                </div>
              </section>
            )}

            <section>
              <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
                <div className="flex items-center gap-2 text-sm font-medium text-ink min-w-0">
                  <Sparkles className="w-4 h-4 text-accent shrink-0" />
                  <span className="truncate">{t("banking.entAiTitle")}</span>
                </div>
                <div className="flex items-center gap-3">
                  <DownloadInsightButton ai={ai} title={detail.bank_name} eyebrow="SDQ · Financiero" subtitle={t("banking.entAiTitle")} />
                  <DeepToggle deep={deep} onToggle={() => setDeep((d) => !d)} disabled={aiLoading} />
                  <AudienceSelector value={audience} onChange={setAudience} />
                </div>
              </div>
              <AiInsightBody
                loading={aiLoading}
                ai={ai}
                unavailableHint={t("banking.entAiUnavailable")}
              />
            </section>
          </>
        )}
      </InsightDrawerShell>

      {/* drill from a sub-component's driver/drag into the indicator drawer */}
      {indicatorKey && (
        <IndicatorDetailDrawer bankId={bankId} indicatorKey={indicatorKey} entityType={detail?.entity_type} onClose={() => setIndicatorKey(null)} />
      )}
    </>
  );
}

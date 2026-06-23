import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Sparkles, TrendingUp, Users } from "lucide-react";
import { TrendChart } from "./TrendChart";
import { entityTypeLabel } from "../entityTypes";
import { StateBlock, Skeleton } from "@/shared/ui/primitives";
import { InsightDrawerShell } from "@/shared/ui/InsightDrawerShell";
import { AiInsightBody } from "@/shared/ui/AiInsightBody";
import { DeepToggle } from "@/shared/ui/DeepToggle";
import { DownloadInsightButton } from "@/shared/ui/DownloadInsightButton";
import { useTwoPhaseInsight } from "@/shared/ui/useTwoPhaseInsight";
import { fmtNum } from "@/shared/lib/format";
import { getIndicatorDetail, type IndicatorDetail } from "../api";
import { useAudience } from "../audience";
import { AudienceSelector } from "./AudienceSelector";

interface Props {
  bankId: string;
  indicatorKey: string;
  entityType?: string | null;
  onClose: () => void;
}

function scoreColor(score: number): string {
  if (score >= 85) return "text-ok bg-ok-soft";
  if (score >= 70) return "text-accent bg-accent-soft";
  if (score >= 55) return "text-warn bg-warn-soft";
  return "text-alert bg-alert-soft";
}

// Maps the backend `direction` value to its translation key.
const DIRECTION_KEY: Record<string, string> = {
  higher: "banking.indDirHigher",
  lower: "banking.indDirLower",
  target: "banking.indDirTarget",
};

function fmtRaw(raw: number | null, unit: string): string {
  if (raw === null || raw === undefined) return "—";
  if (unit === "índice") return fmtNum(raw, 0);
  if (unit === "veces") return `${fmtNum(raw, 2)}×`;
  if (unit === "ratio") return fmtNum(raw, 2);
  return `${fmtNum(raw, 2)}%`;
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
      {/* score track with median tick + this entity marker */}
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

export function IndicatorDetailDrawer({ bankId, indicatorKey, entityType, onClose }: Props) {
  const { t } = useTranslation();
  const [audience, setAudience] = useAudience();
  const [deep, setDeep] = useState(false);
  const { data: detail, ai, loading, aiLoading, error } = useTwoPhaseInsight<IndicatorDetail>(
    (withAi) => getIndicatorDetail(bankId, indicatorKey, withAi, audience, deep),
    `${bankId}:${indicatorKey}:${audience}:${deep}`,
    { pickAi: (d) => d.ai_insight, shouldFetchAi: (d) => d.latest.available },
  );

  return (
    <InsightDrawerShell
      eyebrow={detail?.bank_name ?? t("banking.indEyebrowFallback")}
      title={detail ? t(`indicators.${detail.indicator}`, detail.label) : t("banking.indTitleFallback")}
      onClose={onClose}
    >
      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      ) : error || !detail ? (
        <StateBlock kind="error" message={t("banking.indError")} />
      ) : (
        <>
          {/* value + score */}
          <div className="flex items-end justify-between gap-4">
            <div className="min-w-0">
              <div className="text-xs text-muted mb-1">
                {t(`sub.${detail.sub_component}`, detail.sub_component)} · {DIRECTION_KEY[detail.direction] ? t(DIRECTION_KEY[detail.direction]) : ""}
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
                <TrendingUp className="w-4 h-4 text-muted" /> {t("banking.indTrendTitle")}
              </div>
              <TrendChart data={detail.trend.map((pt) => ({ period: pt.period_end, score: pt.score }))} />
            </section>
          )}

          {/* peers */}
          {detail.peers && (detail.peers.sector || detail.peers.entity_type) && (
            <section>
              <div className="flex items-center gap-2 mb-3 text-sm font-medium text-ink">
                <Users className="w-4 h-4 text-muted" /> {t("banking.peerTitle")}
              </div>
              <div className="space-y-4">
                <PeerRow label={t("banking.peerSector")} stats={detail.peers.sector} score={detail.latest.score} />
                <PeerRow
                  label={t("banking.peerSameType", { type: entityType ? entityTypeLabel(entityType, t) : (detail.peers.entity_type_label ?? "—") })}
                  stats={detail.peers.entity_type}
                  score={detail.latest.score}
                />
              </div>
            </section>
          )}

          {/* AI insight */}
          <section>
            <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
              <div className="flex items-center gap-2 text-sm font-medium text-ink min-w-0">
                <Sparkles className="w-4 h-4 text-accent shrink-0" />
                <span className="truncate">{t("banking.indAiTitle")}</span>
              </div>
              {detail.latest.available && (
                <div className="flex items-center gap-3">
                  <DownloadInsightButton ai={ai} title={t(`indicators.${detail.indicator}`, detail.label)} eyebrow="SDQ · Financiero" subtitle={detail.bank_name} />
                  <DeepToggle deep={deep} onToggle={() => setDeep((d) => !d)} disabled={aiLoading} />
                  <AudienceSelector value={audience} onChange={setAudience} />
                </div>
              )}
            </div>
            <AiInsightBody
              loading={aiLoading}
              ai={ai}
              unavailableHint={t("banking.indAiUnavailable")}
            />
          </section>
        </>
      )}
    </InsightDrawerShell>
  );
}

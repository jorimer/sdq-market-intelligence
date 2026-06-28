import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Sparkles } from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { StateBlock, Skeleton } from "@/shared/ui/primitives";
import { InsightDrawerShell } from "@/shared/ui/InsightDrawerShell";
import { AiInsightBody } from "@/shared/ui/AiInsightBody";
import { DeepToggle } from "@/shared/ui/DeepToggle";
import { DownloadInsightButton } from "@/shared/ui/DownloadInsightButton";
import { AudienceTabs } from "@/shared/ui/AudienceTabs";
import { useTwoPhaseInsight } from "@/shared/ui/useTwoPhaseInsight";
import { useAudiencePref } from "@/shared/lib/useAudiencePref";
import { fmtNum } from "@/shared/lib/format";
import { PENSION_AUDIENCES, PensionTrendPoint } from "../api";

interface Drillable {
  ai_insight: { text: string; model_used: string; from_cache: boolean } | null;
}

/** Small theme-aware trend line for a drill-down (generic value axis). */
export function PensionTrend({ points, unit }: { points: PensionTrendPoint[]; unit?: string | null }) {
  if (points.length < 2) return null;
  const fmt = (v: number) => (unit === "%" ? `${fmtNum(v, 1)}%` : fmtNum(v, v >= 1000 ? 0 : 2));
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={points} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
        <XAxis dataKey="period" tick={{ fontSize: 10, fill: "var(--muted)" }} stroke="var(--border-strong)"
               interval="preserveStartEnd" minTickGap={40} />
        <YAxis tick={{ fontSize: 10, fill: "var(--muted)" }} stroke="var(--border-strong)" width={44}
               tickFormatter={(v) => fmt(v as number)} />
        <Tooltip
          formatter={(v: number) => [fmt(v), ""]}
          contentStyle={{ borderRadius: 8, fontSize: 12, background: "var(--surface)", border: "1px solid var(--border)", color: "var(--ink)" }}
        />
        <Line type="monotone" dataKey="value" stroke="var(--c1)" strokeWidth={2} dot={false} activeDot={{ r: 5 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Peer comparison bars (one row per AFP), highlighting the focused one. */
export function PeerBars(
  { peers, focusAfp, unit }: { peers: { afp: string; raw: number | null }[]; focusAfp: string; unit?: string | null },
) {
  const vals = peers.map((p) => p.raw).filter((v): v is number => v != null);
  const max = vals.length ? Math.max(...vals) : 0;
  const fmt = (v: number) => (unit === "%" ? `${fmtNum(v, 2)}%` : fmtNum(v, v >= 1000 ? 0 : 2));
  const sorted = [...peers].sort((a, b) => (b.raw ?? -Infinity) - (a.raw ?? -Infinity));
  return (
    <div className="space-y-2">
      {sorted.map((p) => {
        const w = max > 0 && p.raw != null ? (p.raw / max) * 100 : 0;
        const focus = p.afp === focusAfp;
        return (
          <div key={p.afp} className="flex items-center gap-3">
            <div className={"w-28 shrink-0 truncate text-sm " + (focus ? "text-ink font-semibold" : "text-body")} title={p.afp}>{p.afp}</div>
            <div className="relative h-4 flex-1 min-w-0 rounded-[5px] bg-surface2">
              <div className={"absolute inset-y-0 left-0 rounded-[5px] " + (focus ? "bg-accent" : "bg-accent/40")} style={{ width: `${w}%` }} />
            </div>
            <div className="w-16 shrink-0 text-right text-sm mono tabular-nums text-ink">{p.raw != null ? fmt(p.raw) : "—"}</div>
          </div>
        );
      })}
    </div>
  );
}

interface Props<T extends Drillable> {
  eyebrow: ReactNode;
  title: string;
  depsKey: string;
  fetcher: (withAi: boolean, audience: string, deep: boolean) => Promise<T>;
  renderDetail: (data: T) => ReactNode;
  /** Skip the AI round-trip when the item has no data to reason about. */
  shouldFetchAi?: (data: T) => boolean;
  onClose: () => void;
}

/** Right-side drill-down drawer for one pension indicator/dimension/holding: deterministic
 * detail (rendered immediately) + its own two-phase Cerebro insight, mirroring banking. */
export function PensionDrillDrawer<T extends Drillable>(
  { eyebrow, title, depsKey, fetcher, renderDetail, shouldFetchAi, onClose }: Props<T>,
) {
  const { t } = useTranslation();
  const [audience, setAudience] = useAudiencePref("sdq.pension.audience", PENSION_AUDIENCES);
  const [deep, setDeep] = useState(false);
  const { data, ai, loading, aiLoading, error } = useTwoPhaseInsight<T>(
    (withAi) => fetcher(withAi, audience, deep),
    `${depsKey}:${audience}:${deep}`,
    { pickAi: (d) => d.ai_insight, shouldFetchAi },
  );

  return (
    <InsightDrawerShell eyebrow={eyebrow} title={title} onClose={onClose}>
      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      ) : error || !data ? (
        <StateBlock kind="error" message={t("pension.drillError")} />
      ) : (
        <>
          {renderDetail(data)}
          <section>
            <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
              <div className="flex items-center gap-2 text-sm font-medium text-ink min-w-0">
                <Sparkles className="w-4 h-4 text-accent shrink-0" />
                <span className="truncate">{t("pension.drillAiTitle")}</span>
              </div>
              <div className="flex items-center gap-3">
                <DownloadInsightButton ai={ai} title={title} eyebrow="SDQ · Pensiones" subtitle={t("pension.drillAiTitle")} />
                <DeepToggle deep={deep} onToggle={() => setDeep((d) => !d)} disabled={aiLoading} />
              </div>
            </div>
            <div className="mb-3">
              <AudienceTabs value={audience} onChange={setAudience} options={PENSION_AUDIENCES}
                            labelPrefix="pension.audience" ariaLabelKey="pension.audienceLabel" />
            </div>
            <AiInsightBody loading={aiLoading} ai={ai} unavailableHint={t("pension.drillAiUnavailable")} />
          </section>
        </>
      )}
    </InsightDrawerShell>
  );
}

import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { PiggyBank, Info } from "lucide-react";
import {
  Card,
  CardHead,
  StatTile,
  StateBlock,
  LoadingGrid,
  Chip,
} from "@/shared/ui/primitives";
import { fmtNum, fmtPct } from "@/shared/lib/format";
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import { AudienceTabs } from "@/shared/ui/AudienceTabs";
import { useAudiencePref } from "@/shared/lib/useAudiencePref";
import {
  getPensionRankings,
  getPensionEntityDetail,
  getPensionEntityInsight,
  PENSION_AUDIENCES,
  PensionRankRow,
  PensionDetail,
} from "../api";

type Status = "loading" | "error" | "ready";

/** Honest banner: the ISA is partial (solvency gap) and the score is relative. */
function PartialNote() {
  const { t } = useTranslation();
  return (
    <div className="flex items-start gap-2 rounded-[10px] bg-surface2 p-3 text-sm text-muted">
      <Info size={16} className="mt-0.5 shrink-0 text-accent" />
      <span>{t("pension.isaPartialNote")}</span>
    </div>
  );
}

/** One AFP's dimension breakdown (score bars + provenance). */
function DetailCard({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const [detail, setDetail] = useState<PensionDetail | null>(null);
  const [state, setState] = useState<Status>("loading");
  const [audience, setAudience] = useAudiencePref("sdq.pension.audience", PENSION_AUDIENCES);

  useEffect(() => {
    setState("loading");
    getPensionEntityDetail(slug)
      .then((d) => { setDetail(d); setState("ready"); })
      .catch(() => setState("error"));
  }, [slug]);

  if (state === "loading") return <Card><LoadingGrid /></Card>;
  if (state === "error" || !detail?.found)
    return <Card><StateBlock kind="error" message={t("pension.detailError")} /></Card>;

  const d = detail;
  return (
    <>
      <Card>
        <CardHead
          icon={PiggyBank}
          title={d.name}
          subtitle={t("pension.detailSubtitle", { period: d.period ?? "—" })}
          right={
            <div className="flex items-center gap-2">
              {d.overall_score != null ? (
                <Chip tone="accent">
                  {t("pension.isaRelative")}: {fmtNum(d.overall_score, 1)}
                </Chip>
              ) : (
                <Chip tone="muted">{t("pension.insufficientData")}</Chip>
              )}
              {d.coverage != null && (
                <Chip tone="muted">{t("pension.coverage")}: {fmtPct(d.coverage * 100, 0)}</Chip>
              )}
            </div>
          }
        />
        <div className="mt-3 space-y-2">
          {d.dimensions.map((dim) => {
            const isGap = dim.provenance === "brecha";
            const pct = dim.score ?? 0;
            return (
              <div key={dim.key} className="flex items-center gap-3">
                <div className="w-44 shrink-0 truncate text-sm text-body" title={dim.label}>
                  {dim.label}
                  <span className="ml-1 text-[11px] text-muted">({fmtPct(dim.weight * 100, 0)})</span>
                </div>
                <div className="relative h-5 flex-1 min-w-0 rounded-[6px] bg-surface2">
                  {dim.present && (
                    <div
                      className="absolute inset-y-0 left-0 rounded-[6px] bg-accent"
                      style={{ width: `${pct}%` }}
                    />
                  )}
                </div>
                <div className="w-16 shrink-0 text-right font-display text-sm font-extrabold text-ink mono">
                  {dim.present ? fmtNum(dim.score, 0) : "—"}
                </div>
                <div className="w-24 shrink-0">
                  {isGap ? (
                    <Chip tone="warn">{t("pension.provGap")}</Chip>
                  ) : dim.present ? (
                    <Chip tone="ok">{t("pension.provReal")}</Chip>
                  ) : (
                    <Chip tone="muted">{t("pension.noData")}</Chip>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      <div className="mt-5">
        <AiInsightCard
          title={t("pension.entityInsightTitle", { name: d.name })}
          subtitle={t("pension.entityInsightSubtitle")}
          depsKey={`${slug}:${audience}`}
          fetcher={() => getPensionEntityInsight(slug, audience)}
          deepFetcher={(deep) => getPensionEntityInsight(slug, audience, deep)}
          actions={
            <AudienceTabs
              value={audience}
              onChange={setAudience}
              options={PENSION_AUDIENCES}
              labelPrefix="pension.audience"
              ariaLabelKey="pension.audienceLabel"
            />
          }
        />
      </div>
    </>
  );
}

export function AfpRankingTab() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<Status>("loading");
  const [rows, setRows] = useState<PensionRankRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const data = await getPensionRankings();
      setRows(data.rankings);
      // Always select an AFP so the detail + AI insight always render: prefer the first
      // scored one, but fall back to the first row when none is scoreable yet (e.g. during
      // a data re-sync) — otherwise the detail/insight card silently disappears.
      setSelected((prev) =>
        prev
        ?? data.rankings.find((r) => r.overall_score != null)?.slug
        ?? data.rankings[0]?.slug
        ?? null);
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (status === "loading") return <LoadingGrid />;
  if (status === "error")
    return <StateBlock kind="error" message={t("pension.rankingsError")} action={<button onClick={load} className="btn btn-ghost">{t("common_retry")}</button>} />;
  if (!rows.length) return <StateBlock kind="empty" message={t("pension.emptyNoData")} />;

  return (
    <div className="space-y-5">
      <PartialNote />
      <Card>
        <CardHead title={t("pension.rankingTitle")} subtitle={t("pension.rankingSubtitle")} />
        <div className="mt-3 divide-y divide-line">
          {rows.map((r) => {
            const active = r.slug === selected;
            const scored = r.overall_score != null;
            return (
              <button
                key={r.slug}
                type="button"
                onClick={() => setSelected(r.slug)}
                className={
                  "flex w-full items-center gap-3 py-2.5 text-left transition-colors " +
                  (active ? "bg-surface2" : "hover:bg-surface2/50")
                }
              >
                <div className="w-8 shrink-0 text-center font-display text-sm font-extrabold text-muted mono">
                  {r.rank ?? "—"}
                </div>
                <div className="flex-1 min-w-0 truncate text-sm text-body">{r.name}</div>
                {r.coverage != null && (
                  <Chip tone="muted">{fmtPct(r.coverage * 100, 0)}</Chip>
                )}
                <div className="w-28 shrink-0 text-right">
                  {scored ? (
                    <span className="font-display text-base font-extrabold text-ink mono">{fmtNum(r.overall_score, 1)}</span>
                  ) : (
                    <span className="text-xs text-muted">{t("pension.insufficientData")}</span>
                  )}
                </div>
              </button>
            );
          })}
        </div>
        <div className="mt-3">
          <StatTile label={t("pension.isaRelative")} value={t("pension.isaScaleHint")} />
        </div>
      </Card>

      {selected && <DetailCard slug={selected} />}
    </div>
  );
}

import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Users, ListOrdered, BarChart3, FileText } from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  Gauge,
  BandBadge,
  StatTile,
  Chip,
  Tabs,
  StateBlock,
  LoadingGrid,
} from "@/shared/ui/primitives";
import { DimensionBreakdown, DimensionRow } from "@/shared/ui/DimensionBreakdown";
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import { AudienceTabs } from "@/shared/ui/AudienceTabs";
import { useAudiencePref } from "@/shared/lib/useAudiencePref";
import { bandFor, toneVar } from "@/shared/lib/bands";
import { fmtNum } from "@/shared/lib/format";
import {
  getIndicators,
  getDataset,
  getPublications,
  getRegionInsight,
  SOCIAL_AUDIENCES,
  IndicatorsResult,
  IdmDataset,
  OnePublication,
} from "../api";
import { REGION_NAMES, IDM_DIM_VARS } from "../data";
import { ValidationTab } from "../components/ValidationTab";

type Status = "loading" | "error" | "ready";

/** Real-vs-rubric tag for one IDM dimension, from the dataset's sources map. */
function dimTag(
  sources: Record<string, string> | undefined,
  dimKey: string,
  t: TFunction,
): DimensionRow["tag"] {
  const vars = IDM_DIM_VARS[dimKey] ?? [];
  if (!sources || vars.length === 0) return undefined;
  const live = vars.filter((v) => sources[v] === "live").length;
  if (live === 0) return { text: t("widgets.tagRubric"), ok: false };
  if (live === vars.length) return { text: t("widgets.tagLive"), ok: true };
  return { text: t("widgets.tagPartialLive", { n: live, total: vars.length }), ok: true };
}

export function SocialDevPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<Status>("loading");
  const [data, setData] = useState<IndicatorsResult | null>(null);
  const [ds, setDs] = useState<IdmDataset | null>(null);
  const [selected, setSelected] = useState("ozama");
  const [audience, setAudience] = useAudiencePref("sdq.social.audience", SOCIAL_AUDIENCES);
  const [tab, setTab] = useState("distribucion");
  const [pubs, setPubs] = useState<OnePublication[]>([]);

  const nameOf = (key: string) => REGION_NAMES[key] ?? key;

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const [ind, dataset] = await Promise.all([getIndicators(), getDataset()]);
      setData(ind);
      setDs(dataset);
      setSelected((prev) =>
        ind.indicators.some((e) => e.entity_key === prev)
          ? prev
          : ind.indicators[0]?.entity_key ?? prev,
      );
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // ONE studies (digest IA) — best-effort, independent of the index.
  useEffect(() => {
    let active = true;
    getPublications()
      .then((r) => { if (active) setPubs(r.publications.filter((p) => p.status === "ok")); })
      .catch(() => { if (active) setPubs([]); });
    return () => { active = false; };
  }, []);

  const head = (
    <PageHead
      eyebrow={t("social.eyebrow")}
      title={t("social.title")}
      sub={t("social.sub")}
    />
  );

  if (status === "loading") return <div>{head}<LoadingGrid /></div>;
  if (status === "error")
    return (
      <div>
        {head}
        <StateBlock
          kind="error"
          message={t("social.errorLoad")}
          action={<button onClick={load} className="btn btn-ghost">{t("common_retry")}</button>}
        />
      </div>
    );

  const entities = data!.indicators;
  if (entities.length === 0)
    return (
      <div>
        {head}
        <StateBlock kind="empty" message={t("social.emptyNoSnapshot")} />
      </div>
    );

  const dist = data!.distribution;
  const cur = entities.find((e) => e.entity_key === selected);
  const sources = ds?.sources[selected];
  const band = bandFor(cur?.development_score, t);
  const ranking = [...entities].sort((a, b) => b.development_score - a.development_score);

  const rows: DimensionRow[] = cur
    ? Object.entries(cur.breakdown).map(([key, d]) => ({
        key,
        label: t(`social.dims.${key}`, key),
        score: d.score,
        weight: d.weight,
        contribution: d.contribution,
        tag: dimTag(sources, key, t),
      }))
    : [];

  const lo = dist.min ?? 0;
  const hi = dist.max ?? 100;
  const span = Math.max(1, hi - lo);
  const dimCount = Object.keys(IDM_DIM_VARS).length;
  const liveDims = sources
    ? Object.keys(IDM_DIM_VARS).filter((k) => dimTag(sources, k, t)?.ok).length
    : 0;

  return (
    <div>
      <PageHead
        eyebrow={t("social.eyebrow")}
        title={t("social.title")}
        sub={t("social.sub")}
        right={
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="field !w-auto"
            title={t("social.regionSelect")}
          >
            {entities.map((e) => (
              <option key={e.entity_key} value={e.entity_key}>{nameOf(e.entity_key)}</option>
            ))}
          </select>
        }
      />

      <div className="flex flex-wrap items-center gap-2 mb-4 -mt-2">
        <Chip tone={ds?.has_live ? "ok" : "muted"}>
          {t("social.liveDimsChip", { live: liveDims, total: dimCount })}
        </Chip>
        {data!.period && <Chip tone="muted">{data!.period}</Chip>}
        <Chip tone="muted">{t("social.regionsCount", { n: entities.length })}</Chip>
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        {/* Hero */}
        <Card className="lg:col-span-1 flex flex-col items-center text-center">
          <div className="text-xs text-muted mb-3 w-full truncate">{nameOf(selected)}</div>
          <Gauge score={cur?.development_score} band={band} />
          <div className="mt-3"><BandBadge band={band} /></div>
          <div className="text-xs text-muted mt-3">{t("social.heroCount", { n: dist.n })}</div>
        </Card>

        {/* Tabs */}
        <div className="lg:col-span-2">
          <Card>
            <Tabs
              tabs={[
                { id: "distribucion", label: t("social.tabDistribution") },
                { id: "desglose", label: t("social.tabBreakdown") },
                { id: "ranking", label: t("social.tabRanking") },
                { id: "validacion", label: t("social.tabValidation") },
                { id: "estudios", label: pubs.length ? t("social.tabStudiesN", { n: pubs.length }) : t("social.tabStudies") },
              ]}
              active={tab}
              onChange={setTab}
            />
            <div className="pt-5">
              {tab === "distribucion" && (
                <>
                  <CardHead
                    icon={BarChart3}
                    title={t("social.distTitle")}
                    subtitle={t("social.distSubtitle")}
                  />
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
                    <StatTile label={t("social.statMean")} value={fmtNum(dist.mean, 1)} />
                    <StatTile label={t("social.statMin")} value={fmtNum(dist.min, 1)} />
                    <StatTile label={t("social.statMax")} value={fmtNum(dist.max, 1)} />
                    <StatTile label={t("social.statSpread")} value={fmtNum(dist.spread, 1)} />
                  </div>
                  <div className="rounded-[10px] bg-surface2 p-4">
                    <div className="relative h-10">
                      {ranking.map((e) => {
                        const x = ((e.development_score - lo) / span) * 100;
                        const b = bandFor(e.development_score);
                        return (
                          <div
                            key={e.entity_key}
                            title={`${nameOf(e.entity_key)}: ${fmtNum(e.development_score, 1)}`}
                            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3.5 h-3.5 rounded-full border-2 border-surface"
                            style={{ left: `${x}%`, background: toneVar(b.tone) }}
                          />
                        );
                      })}
                    </div>
                    <div className="flex justify-between mono text-[11px] text-muted mt-1">
                      <span>{fmtNum(dist.min, 0)}</span>
                      <span>{t("social.cv", { v: dist.cv != null ? fmtNum(dist.cv * 100, 1) + "%" : "—" })}</span>
                      <span>{fmtNum(dist.max, 0)}</span>
                    </div>
                  </div>
                </>
              )}

              {tab === "desglose" && (
                <>
                  <CardHead
                    icon={Users}
                    title={t("social.breakdownTitle")}
                    subtitle={t("social.breakdownSubtitle", { region: nameOf(selected) })}
                  />
                  <DimensionBreakdown rows={rows} />
                </>
              )}

              {tab === "ranking" && (
                <>
                  <CardHead icon={ListOrdered} title={t("social.rankingTitle")} subtitle={t("social.rankingSubtitle")} />
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-muted border-b border-line">
                        <th className="py-2 px-1 font-medium">#</th>
                        <th className="py-2 px-1 font-medium">{t("social.colRegion")}</th>
                        <th className="py-2 px-1 font-medium text-right">IDM</th>
                        <th className="py-2 px-1 font-medium">{t("social.colBand")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ranking.map((e, i) => {
                        const b = bandFor(e.development_score, t);
                        return (
                          <tr
                            key={e.entity_key}
                            className={`border-b border-line/60 last:border-0 ${
                              e.entity_key === selected ? "bg-accent-soft/40" : ""
                            }`}
                          >
                            <td className="py-2.5 px-1 mono text-muted">{i + 1}</td>
                            <td className="py-2.5 px-1 text-ink truncate">{nameOf(e.entity_key)}</td>
                            <td className="py-2.5 px-1 text-right mono font-semibold text-ink">
                              {fmtNum(e.development_score, 1)}
                            </td>
                            <td className="py-2.5 px-1"><BandBadge band={b} /></td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </>
              )}

              {tab === "validacion" && <ValidationTab />}

              {tab === "estudios" && (
                <>
                  <CardHead
                    icon={FileText}
                    title={t("social.studiesTitle")}
                    subtitle={t("social.studiesSubtitle")}
                  />
                  {pubs.length === 0 ? (
                    <p className="text-sm text-muted">{t("social.studiesEmpty")}</p>
                  ) : (
                    <div className="space-y-3">
                      {pubs.map((p) => (
                        <div key={p.id} className="rounded-[10px] border border-line bg-surface2 p-3">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 flex-1">
                              <div className="text-sm font-semibold text-ink truncate">{p.report_name}</div>
                              <div className="text-xs text-muted mono mt-0.5">{p.period}</div>
                            </div>
                            <a
                              href={p.landing_url}
                              target="_blank"
                              rel="noreferrer"
                              className="shrink-0 text-xs text-accent hover:underline"
                            >
                              {t("social.studyLink")}
                            </a>
                          </div>
                          {p.resumen && <p className="text-xs text-body mt-2">{p.resumen}</p>}
                          {p.hallazgos?.length > 0 && (
                            <ul className="mt-2 space-y-1">
                              {p.hallazgos.slice(0, 4).map((h, i) => (
                                <li key={i} className="text-xs text-muted flex gap-1.5">
                                  <span className="text-accent">·</span>
                                  <span className="min-w-0">{h}</span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          </Card>
        </div>
      </div>

      <div className="mt-5">
        <AiInsightCard
          title={t("social.insightTitle")}
          subtitle={t("social.insightSubtitle", { region: nameOf(selected) })}
          depsKey={`${selected}:${audience}`}
          fetcher={() => getRegionInsight(selected, audience)}
          deepFetcher={(deep) => getRegionInsight(selected, audience, deep)}
          actions={
            <AudienceTabs
              value={audience}
              onChange={setAudience}
              options={SOCIAL_AUDIENCES}
              labelPrefix="social.audience"
              ariaLabelKey="social.audienceLabel"
            />
          }
        />
      </div>
    </div>
  );
}

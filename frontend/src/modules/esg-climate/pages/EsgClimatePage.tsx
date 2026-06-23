import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Leaf, ListOrdered, ShieldCheck } from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  Gauge,
  Chip,
  Tabs,
  StatTile,
  StateBlock,
  LoadingGrid,
} from "@/shared/ui/primitives";
import { DimensionBreakdown, DimensionRow } from "@/shared/ui/DimensionBreakdown";
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import { AudienceTabs } from "@/shared/ui/AudienceTabs";
import { useAudiencePref } from "@/shared/lib/useAudiencePref";
import { Band } from "@/shared/lib/bands";
import { fmtNum } from "@/shared/lib/format";
import { getIndicators, getCountryScore, getCountryInsight, getBacktest, CLIMATE_AUDIENCES, IRCIndicator, IRCCountryDetail, IRCBacktest } from "../api";
import { IRC_DIM_VARS } from "../data";

type Status = "loading" | "error" | "ready";

// Higher IRC = more resilient / lower climate risk.
function ircBand(score: number | null | undefined, t: TFunction): Band {
  if (score == null) return { label: t("esg.band.noData"), tone: "muted" };
  if (score >= 60) return { label: t("esg.band.high"), tone: "ok" };
  if (score >= 40) return { label: t("esg.band.moderate"), tone: "warn" };
  return { label: t("esg.band.low"), tone: "alert" };
}

/** Real-vs-rubric tag for one IRC dimension, from the source map. */
function dimTag(
  sources: Record<string, string> | undefined,
  dimKey: string,
  t: TFunction,
): DimensionRow["tag"] {
  const vars = IRC_DIM_VARS[dimKey] ?? [];
  if (!sources || vars.length === 0) return undefined;
  const live = vars.filter((v) => sources[v] === "live").length;
  if (live === 0) return { text: t("esg.tag.rubric"), ok: false };
  if (live === vars.length) return { text: t("esg.tag.live"), ok: true };
  return { text: t("esg.tag.partialLive", { n: live, total: vars.length }), ok: true };
}

export function EsgClimatePage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<Status>("loading");
  const [countries, setCountries] = useState<IRCIndicator[]>([]);
  const [detail, setDetail] = useState<IRCCountryDetail | null>(null);
  const [selected, setSelected] = useState("DOM");
  const [audience, setAudience] = useAudiencePref("sdq.esg.audience", CLIMATE_AUDIENCES);
  const [tab, setTab] = useState("desglose");
  const [backtest, setBacktest] = useState<IRCBacktest | null>(null);

  useEffect(() => {
    getBacktest().then(setBacktest).catch(() => setBacktest(null));
  }, []);

  const loadDetail = useCallback(async (key: string) => {
    try {
      setDetail(await getCountryScore(key));
    } catch {
      setDetail(null);
    }
  }, []);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const r = await getIndicators();
      setCountries(r.indicators);
      setSelected((prev) =>
        r.indicators.some((c) => c.entity_key === prev)
          ? prev
          : r.indicators.find((c) => c.entity_key === "DOM")?.entity_key
            ?? r.indicators[0]?.entity_key ?? prev,
      );
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (status === "ready" && selected) loadDetail(selected);
  }, [selected, status, loadDetail]);

  const nameOf = (key: string) =>
    countries.find((c) => c.entity_key === key)?.country_name ?? key;

  const head = (
    <PageHead
      eyebrow={t("esg.eyebrow")}
      title={t("esg.title")}
      sub={t("esg.subFull")}
    />
  );

  if (status === "loading") return <div>{head}<LoadingGrid /></div>;
  if (status === "error")
    return (
      <div>
        {head}
        <StateBlock kind="error" message={t("esg.errorLoad")}
          action={<button onClick={load} className="btn btn-ghost">{t("common_retry")}</button>} />
      </div>
    );

  if (countries.length === 0)
    return (
      <div>
        {head}
        <StateBlock kind="empty" message={t("esg.emptyNoIrc")} />
      </div>
    );

  const cur = countries.find((c) => c.entity_key === selected);
  const band = ircBand(cur?.esg_score, t);
  const ranking = [...countries].sort((a, b) => b.esg_score - a.esg_score); // most resilient first
  const sources = detail?.breakdown?.sources;
  const dims = detail?.breakdown?.dimensions ?? {};
  const rows: DimensionRow[] = Object.entries(dims).map(([key, d]) => ({
    key,
    label: t(`esg.dims.${key}`, key),
    score: d.score,
    weight: d.weight,
    contribution: d.contribution,
    tag: dimTag(sources, key, t),
  }));

  return (
    <div>
      <PageHead
        eyebrow={t("esg.eyebrow")}
        title={t("esg.title")}
        sub={t("esg.subShort", { period: cur?.period ?? "" })}
        right={
          <select value={selected} onChange={(e) => setSelected(e.target.value)}
            className="field !w-auto" title={t("esg.countrySelect")}>
            {countries.map((c) => (
              <option key={c.entity_key} value={c.entity_key}>{c.country_name}</option>
            ))}
          </select>
        }
      />

      <div className="grid lg:grid-cols-3 gap-5">
        {/* Hero */}
        <Card className="lg:col-span-1 flex flex-col items-center text-center">
          <div className="text-xs text-muted mb-1 w-full truncate">{nameOf(selected)}</div>
          <div className="mono text-[10px] uppercase tracking-[0.16em] text-accent mb-2">IRC</div>
          <Gauge score={cur?.esg_score} band={band} />
          <div className="mt-3"><Chip tone={band.tone}>{band.label}</Chip></div>
          <div className="text-xs text-muted mt-3">{t("esg.panelCount", { count: countries.length })}</div>
        </Card>

        {/* Tabs */}
        <div className="lg:col-span-2">
          <Card>
            <Tabs
              tabs={[
                { id: "desglose", label: t("esg.tab.breakdown") },
                { id: "ranking", label: t("esg.tab.ranking") },
                { id: "validacion", label: t("esg.tab.validation") },
              ]}
              active={tab}
              onChange={setTab}
            />
            <div className="pt-5">
              {tab === "desglose" && (
                <>
                  <CardHead icon={Leaf} title={t("esg.breakdownTitle")}
                    subtitle={t("esg.breakdownSubtitle", { country: nameOf(selected) })} />
                  <DimensionBreakdown rows={rows} />
                </>
              )}

              {tab === "ranking" && (
                <>
                  <CardHead icon={ListOrdered} title={t("esg.rankingTitle")}
                    subtitle={t("esg.rankingSubtitle")} />
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-muted border-b border-line">
                        <th className="py-2 px-1 font-medium">#</th>
                        <th className="py-2 px-1 font-medium">{t("esg.colCountry")}</th>
                        <th className="py-2 px-1 font-medium text-right">IRC</th>
                        <th className="py-2 px-1 font-medium">{t("esg.colResilience")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ranking.map((c, i) => {
                        const b = ircBand(c.esg_score, t);
                        return (
                          <tr key={c.entity_key}
                            className={`border-b border-line/60 last:border-0 ${
                              c.entity_key === selected ? "bg-accent-soft/40" : ""}`}>
                            <td className="py-2.5 px-1 mono text-muted">{i + 1}</td>
                            <td className="py-2.5 px-1 text-ink truncate">{c.country_name}</td>
                            <td className="py-2.5 px-1 text-right mono font-semibold text-ink">
                              {fmtNum(c.esg_score, 1)}
                            </td>
                            <td className="py-2.5 px-1"><Chip tone={b.tone}>{b.label}</Chip></td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </>
              )}

              {tab === "validacion" && (
                <>
                  <CardHead icon={ShieldCheck} title={t("esg.validationTitle")}
                    subtitle={t("esg.validationSubtitle")} />
                  {!backtest?.computed ? (
                    <StateBlock kind="empty"
                      message={backtest?.message ?? t("esg.emptyBacktest")} />
                  ) : (
                    <div className="space-y-4">
                      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                        <StatTile label={t("esg.valSpearman")} value={fmtNum(backtest.spearman ?? null, 3)} />
                        <StatTile label={t("esg.valCi")}
                          value={backtest.spearman_ci
                            ? `${fmtNum(backtest.spearman_ci[0] ?? null, 2)} … ${fmtNum(backtest.spearman_ci[1] ?? null, 2)}`
                            : "—"} />
                        <StatTile label={t("esg.valCountries")} value={backtest.n_countries ?? "—"} />
                      </div>
                      <div className="flex items-center gap-2">
                        <Chip tone={backtest.monotonic ? "ok" : "warn"}>
                          {backtest.monotonic ? t("esg.monotonicYes") : t("esg.monotonicNo")}
                        </Chip>
                        <span className="text-xs text-muted">
                          {t("esg.monotonicHint")}
                        </span>
                      </div>
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-left text-xs text-muted border-b border-line">
                            <th className="py-2 px-1 font-medium">{t("esg.colIrcBand")}</th>
                            <th className="py-2 px-1 font-medium text-right">{t("esg.colCountries")}</th>
                            <th className="py-2 px-1 font-medium text-right">{t("esg.colDeaths")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(backtest.by_band ?? []).map((b) => (
                            <tr key={b.band} className="border-b border-line/60 last:border-0">
                              <td className="py-2.5 px-1 text-ink">{b.band}</td>
                              <td className="py-2.5 px-1 text-right mono text-body">{b.n}</td>
                              <td className="py-2.5 px-1 text-right mono text-ink">
                                {fmtNum(b.mean_climate_deaths_per_100k ?? null, 3)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {backtest.note && <p className="text-xs text-muted">{backtest.note}</p>}
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
          title={t("esg.insightTitle")}
          subtitle={t("esg.insightSubtitle", { country: nameOf(selected) })}
          depsKey={`${selected}:${audience}`}
          fetcher={() => getCountryInsight(selected, audience)}
          actions={
            <AudienceTabs
              value={audience}
              onChange={setAudience}
              options={CLIMATE_AUDIENCES}
              labelPrefix="esg.audience"
              ariaLabelKey="esg.audienceLabel"
            />
          }
        />
      </div>
    </div>
  );
}

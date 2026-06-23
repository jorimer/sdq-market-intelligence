import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Scale, ListOrdered, SlidersHorizontal, ShieldAlert } from "lucide-react";
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import { AudienceTabs } from "@/shared/ui/AudienceTabs";
import { useAudiencePref } from "@/shared/lib/useAudiencePref";
import {
  PageHead,
  Card,
  CardHead,
  Gauge,
  BandBadge,
  Chip,
  Tabs,
  StateBlock,
  LoadingGrid,
} from "@/shared/ui/primitives";
import { DimensionBreakdown, DimensionRow } from "@/shared/ui/DimensionBreakdown";
import { ValidationTab } from "../components/ValidationTab";
import { riskBandFor } from "@/shared/lib/bands";
import { fmtNum } from "@/shared/lib/format";
import { useApp } from "@/shared/context/AppContext";
import {
  getWeights,
  getDataset,
  scoreCountry,
  MPR_AUDIENCES,
  saveSnapshot,
  IRMPResult,
  IRMPWeights,
} from "../api";
import {
  SAMPLE_REGIONAL,
  COUNTRY_NAMES,
} from "../data";

type Status = "loading" | "error" | "ready";
type Dataset = Record<string, Record<string, number>>;
type SourceMap = Record<string, Record<string, "live" | "rubric">>;

interface LiveInfo {
  period: string | null;
  covered: number;        // countries with ≥1 live variable
  total: number;
  variables: number;      // distinct live/declared variables
  live: boolean;
}

function periodEndFor(period: string): string {
  const q: Record<string, string> = { Q1: "03-31", Q2: "06-30", Q3: "09-30", Q4: "12-31" };
  const m = period.match(/^(\d{4})-(Q[1-4])$/);
  if (m) return `${m[1]}-${q[m[2]]}`;
  if (/^\d{4}$/.test(period)) return `${period}-12-31`;
  return "2025-12-31";
}

export function MacroPoliticalRiskPage() {
  const { t } = useTranslation();
  const { period } = useApp();
  const [status, setStatus] = useState<Status>("loading");
  const [results, setResults] = useState<Record<string, IRMPResult>>({});
  const [weights, setWeights] = useState<IRMPWeights | null>(null);
  const [selected, setSelected] = useState("DO");
  const [audience, setAudience] = useAudiencePref("sdq.mpr.audience", MPR_AUDIENCES);
  const [tab, setTab] = useState("desglose");
  const [saved, setSaved] = useState<string | null>(null);
  const [dataset, setDataset] = useState<Dataset>(SAMPLE_REGIONAL);
  const [sources, setSources] = useState<SourceMap>({});
  const [dataPeriod, setDataPeriod] = useState<string | null>(null);
  const [liveInfo, setLiveInfo] = useState<LiveInfo>({
    period: null, covered: 0, total: Object.keys(SAMPLE_REGIONAL).length, variables: 0, live: false,
  });

  // Presentation country list: fixture order first, plus any extra country the
  // backend actually scored (so a doctrine/live addition isn't silently hidden
  // from the ranking and selector).
  const codes = [...new Set([...Object.keys(SAMPLE_REGIONAL), ...Object.keys(results)])];

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      // Single source of truth: the backend assembles declared rubric + live data
      // (real wins). Best-effort: if it fails or has no live data, fall back to the
      // illustrative fixture so the page never breaks.
      let data: Dataset = SAMPLE_REGIONAL;
      let smap: SourceMap = {};
      let dperiod: string | null = null;
      let info: LiveInfo = { period: null, covered: 0, total: codes.length, variables: 0, live: false };
      try {
        const asm = await getDataset();
        if (asm.has_live && Object.keys(asm.dataset).length) {
          data = asm.dataset;
          smap = asm.sources;
          dperiod = asm.period;
          const liveVars = new Set<string>();
          let covered = 0;
          for (const iso of Object.keys(asm.sources)) {
            const live = Object.entries(asm.sources[iso]).filter(([, s]) => s === "live");
            if (live.length) covered += 1;
            live.forEach(([v]) => liveVars.add(v));
          }
          info = { period: asm.period, covered, total: Object.keys(asm.dataset).length,
                   variables: liveVars.size, live: covered > 0 };
        }
      } catch {
        /* keep fixture — degradación elegante */
      }

      const dataCodes = Object.keys(data);
      const [w, ...scores] = await Promise.all([
        getWeights(),
        ...dataCodes.map((c) => scoreCountry(c, data)),
      ]);
      const map: Record<string, IRMPResult> = {};
      scores.forEach((s) => (map[s.country_code] = s));
      setWeights(w);
      setResults(map);
      setDataset(data);
      setSources(smap);
      setDataPeriod(dperiod);
      setLiveInfo(info);
      setStatus("ready");
    } catch {
      setStatus("error");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const head = (
    <PageHead
      eyebrow={t("mpr.eyebrow")}
      title={t("mpr.title")}
      sub={t("mpr.sub")}
    />
  );

  if (status === "loading") return <div>{head}<LoadingGrid /></div>;
  if (status === "error")
    return (
      <div>
        {head}
        <StateBlock
          kind="error"
          message={t("mpr.errorLoad")}
          action={<button onClick={load} className="btn btn-ghost">{t("common_retry")}</button>}
        />
      </div>
    );

  const cur = results[selected];
  const band = riskBandFor(cur?.irmp_score, t);
  const sel = sources[selected] ?? {};
  const rows: DimensionRow[] = cur
    ? Object.entries(cur.dimensions).map(([key, d]) => {
        const vars = weights?.dimension_variables[key] ?? [];
        const live = vars.filter((v) => sel[v] === "live").length;
        const tag: DimensionRow["tag"] =
          vars.length === 0 || Object.keys(sel).length === 0
            ? undefined
            : live === vars.length
            ? { text: t("widgets.tagLive"), ok: true }
            : live === 0
            ? { text: t("widgets.tagRubric") }
            : { text: t("widgets.tagPartialLive", { n: live, total: vars.length }), ok: live >= vars.length / 2 };
        return {
          key,
          label: t(`mpr.dims.${key}`, key),
          score: d.score,
          weight: d.weight,
          contribution: d.contribution,
          tag,
        };
      })
    : [];

  const ranking = [...codes]
    .map((c) => results[c])
    .filter(Boolean)
    .sort((a, b) => b.irmp_score - a.irmp_score);

  // Persist at the data vintage (e.g. 2024) so the manual save and the scheduled
  // irmp-snapshot operation key snapshots the same way.
  const snapPeriod = periodEndFor(dataPeriod ?? period);
  const doSave = async () => {
    setSaved(null);
    try {
      await saveSnapshot(selected, dataset, snapPeriod, COUNTRY_NAMES[selected]);
      setSaved(t("mpr.savedOk", { period: snapPeriod }));
    } catch {
      setSaved(t("mpr.savedErr"));
    }
  };

  return (
    <div>
      <PageHead
        eyebrow={t("mpr.eyebrow")}
        title={t("mpr.title")}
        sub={t("mpr.sub")}
        right={
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="field !w-auto"
            title={t("mpr.countrySelect")}
          >
            {codes.map((c) => (
              <option key={c} value={c}>
                {COUNTRY_NAMES[c] ?? c}
              </option>
            ))}
          </select>
        }
      />

      <div className="grid lg:grid-cols-3 gap-5">
        {/* Hero */}
        <Card className="lg:col-span-1 flex flex-col items-center text-center">
          <div className="text-xs text-muted mb-3 truncate w-full">
            {COUNTRY_NAMES[selected] ?? selected}
          </div>
          <Gauge score={cur?.irmp_score} band={band} />
          <div className="mt-3">
            <BandBadge band={band} />
          </div>
          <div className="mt-3 text-xs text-muted">
            {t("mpr.heroPeerSet", { n: cur?.peer_set_size ?? codes.length })}
          </div>
          <div className="mt-2">
            {liveInfo.live ? (
              <Chip tone="ok">
                {t("mpr.liveChip", { vars: liveInfo.variables, period: liveInfo.period, covered: liveInfo.covered, total: liveInfo.total })}
              </Chip>
            ) : (
              <Chip tone="muted">{t("mpr.illustrativeChip")}</Chip>
            )}
          </div>
          <button onClick={doSave} className="btn btn-soft mt-4 w-full">
            {t("mpr.saveSnapshot")}
          </button>
          {saved && <div className="text-xs text-muted mt-2">{saved}</div>}
        </Card>

        {/* Tabs: desglose / ranking */}
        <div className="lg:col-span-2">
          <Card>
            <Tabs
              tabs={[
                { id: "desglose", label: t("mpr.tabBreakdown") },
                { id: "ranking", label: t("mpr.tabRanking") },
                { id: "pesos", label: t("mpr.tabWeights") },
                { id: "validacion", label: t("mpr.tabValidation") },
              ]}
              active={tab}
              onChange={setTab}
            />

            <div className="pt-5">
              {tab === "desglose" && (
                <>
                  <CardHead
                    icon={Scale}
                    title={t("mpr.breakdownTitle")}
                    subtitle={t("mpr.breakdownSubtitle", { country: COUNTRY_NAMES[selected] ?? selected })}
                  />
                  <DimensionBreakdown rows={rows} />
                </>
              )}

              {tab === "ranking" && (
                <>
                  <CardHead
                    icon={ListOrdered}
                    title={t("mpr.rankingTitle")}
                    subtitle={t("mpr.rankingSubtitle")}
                  />
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-muted border-b border-line">
                        <th className="py-2 px-1 font-medium">#</th>
                        <th className="py-2 px-1 font-medium">{t("mpr.colCountry")}</th>
                        <th className="py-2 px-1 font-medium text-right">IRMP</th>
                        <th className="py-2 px-1 font-medium">{t("mpr.colBand")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ranking.map((r, i) => {
                        const b = riskBandFor(r.irmp_score, t);
                        return (
                          <tr
                            key={r.country_code}
                            className={`border-b border-line/60 last:border-0 ${
                              r.country_code === selected ? "bg-accent-soft/40" : ""
                            }`}
                          >
                            <td className="py-2.5 px-1 mono text-muted">{i + 1}</td>
                            <td className="py-2.5 px-1 text-ink truncate">
                              {COUNTRY_NAMES[r.country_code] ?? r.country_code}
                            </td>
                            <td className="py-2.5 px-1 text-right mono font-semibold text-ink">
                              {fmtNum(r.irmp_score, 1)}
                            </td>
                            <td className="py-2.5 px-1">
                              <BandBadge band={b} />
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </>
              )}

              {tab === "pesos" && weights && (
                <>
                  <CardHead
                    icon={SlidersHorizontal}
                    title={t("mpr.weightsTitle")}
                    subtitle={weights.direction}
                  />
                  <div className="space-y-2">
                    {Object.entries(weights.dimension_weights).map(([k, w]) => (
                      <div
                        key={k}
                        className="flex items-center justify-between gap-3 py-1.5 border-b border-line/60 last:border-0"
                      >
                        <span className="text-sm text-ink">{t(`mpr.dims.${k}`, k)}</span>
                        <Chip tone="accent">{Math.round(w * 100)}%</Chip>
                      </div>
                    ))}
                  </div>
                </>
              )}

              {tab === "validacion" && <ValidationTab />}
            </div>
          </Card>
        </div>
      </div>

      {cur && (
        <div className="mt-5">
          <AiInsightCard
            title={t("mpr.insightTitle")}
            subtitle={t("mpr.insightSubtitle", { country: COUNTRY_NAMES[selected] ?? selected, score: fmtNum(cur.irmp_score, 1), band: band.label })}
            icon={ShieldAlert}
            depsKey={`${selected}:${liveInfo.period ?? "fix"}:${audience}`}
            fetcher={() =>
              scoreCountry(selected, dataset, {
                withAi: true,
                countryName: COUNTRY_NAMES[selected],
                audience,
              }).then((r) => r.ai_insight ?? null)
            }
            actions={
              <AudienceTabs
                value={audience}
                onChange={setAudience}
                options={MPR_AUDIENCES}
                labelPrefix="mpr.audience"
                ariaLabelKey="mpr.audienceLabel"
              />
            }
          />
        </div>
      )}
    </div>
  );
}

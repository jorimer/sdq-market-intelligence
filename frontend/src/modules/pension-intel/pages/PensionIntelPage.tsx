import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { PiggyBank, ChevronRight } from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  StatTile,
  StateBlock,
  LoadingGrid,
  Chip,
  Tabs,
} from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import { AudienceTabs } from "@/shared/ui/AudienceTabs";
import { useAudiencePref } from "@/shared/lib/useAudiencePref";
import { AfpRankingTab } from "../components/AfpRankingTab";
import { CarteraTab } from "../components/CarteraTab";
import { PensionDrillDrawer, PensionTrend, PeerBars } from "../components/PensionDrillDrawer";
import {
  getPensionPulse,
  getPensionInsight,
  getPensionIndicator,
  getPensionDimension,
  pulseHasData,
  PENSION_AUDIENCES,
  HEADLINE_CCI,
  HEADLINE_SDP,
  HEADLINE_COMMISSIONS,
  PensionPulse,
} from "../api";

/** Open-drill descriptor for the system tab (an indicator or an AFP's rentabilidad dimension). */
type SysDrill =
  | { kind: "indicator"; code: string; label: string }
  | { kind: "dimension"; slug: string; afp: string };

type Status = "loading" | "error" | "ready";

/** Per-AFP rentabilidad as horizontal bars (leader → laggard), tokens only. */
function DispersionBars({ pulse, onPick }: { pulse: PensionPulse; onPick: (slug: string, name: string) => void }) {
  const { t } = useTranslation();
  const afp = pulse.afp_rentabilidad;
  const ranking = afp.ranking ?? [];
  const max = ranking.length ? Math.max(...ranking.map((r) => r.value)) : 0;

  return (
    <Card>
      <CardHead
        icon={PiggyBank}
        title={t("pension.dispersionTitle")}
        subtitle={t("pension.dispersionSubtitle", { period: afp.period ?? "—" })}
        right={
          afp.spread != null ? (
            <Chip tone="muted">
              {t("pension.spread")}: {fmtNum(afp.spread, 2)} {t("pension.unitPct")}
            </Chip>
          ) : undefined
        }
      />
      <div className="mt-3 space-y-1">
        {ranking.map((r, i) => {
          const pct = max > 0 ? (r.value / max) * 100 : 0;
          const isLeader = i === 0;
          const isLaggard = i === ranking.length - 1 && ranking.length > 1;
          return (
            <button
              key={r.slug}
              type="button"
              onClick={() => onPick(r.slug, r.name)}
              className="flex w-full items-center gap-3 rounded-[8px] px-1.5 py-1 text-left transition-colors hover:bg-surface2/60"
              title={t("pension.drillOpen")}
            >
              <div className="w-32 shrink-0 truncate text-sm text-body" title={r.name}>
                {r.name}
              </div>
              <div className="relative h-5 flex-1 min-w-0 rounded-[6px] bg-surface2">
                <div
                  className="absolute inset-y-0 left-0 rounded-[6px] bg-accent"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <div className="w-16 shrink-0 text-right font-display text-sm font-extrabold text-ink mono">
                {fmtNum(r.value, 2)}
              </div>
              <div className="w-20 shrink-0 flex items-center gap-1">
                {isLeader && <Chip tone="ok">{t("pension.leader")}</Chip>}
                {isLaggard && <Chip tone="warn">{t("pension.laggard")}</Chip>}
                <ChevronRight size={14} className="text-faint ml-auto" />
              </div>
            </button>
          );
        })}
      </div>
    </Card>
  );
}

export function PensionIntelPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<Status>("loading");
  const [pulse, setPulse] = useState<PensionPulse | null>(null);
  const [tab, setTab] = useState("sistema");
  const [sysDrill, setSysDrill] = useState<SysDrill | null>(null);
  const [audience, setAudience] = useAudiencePref("sdq.pension.audience", PENSION_AUDIENCES);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      setPulse(await getPensionPulse());
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const head = (
    <PageHead eyebrow={t("pension.eyebrow")} title={t("pension.title")} sub={t("pension.subDefault")} />
  );

  if (status === "loading") return <div>{head}<LoadingGrid /></div>;
  if (status === "error")
    return (
      <div>
        {head}
        <StateBlock
          kind="error"
          message={t("pension.errorLoad")}
          action={<button onClick={load} className="btn btn-ghost">{t("common_retry")}</button>}
        />
      </div>
    );

  const p = pulse!;
  const has = pulseHasData(p);
  const cci = p.headline?.[HEADLINE_CCI] ?? null;
  const sdp = p.headline?.[HEADLINE_SDP] ?? null;
  const commissions = p.headline?.[HEADLINE_COMMISSIONS] ?? null;

  return (
    <div>
      <PageHead
        eyebrow={t("pension.eyebrow")}
        title={t("pension.title")}
        sub={p.period ? t("pension.subScored", { period: p.period }) : t("pension.subDefault")}
      />

      <Card className="mb-5">
        <Tabs
          tabs={[
            { id: "sistema", label: t("pension.tabSystem") },
            { id: "afp", label: t("pension.tabAfp") },
            { id: "cartera", label: t("pension.tabCartera") },
          ]}
          active={tab}
          onChange={setTab}
        />
      </Card>

      {tab === "afp" && <AfpRankingTab />}

      {tab === "cartera" && <CarteraTab />}

      {tab === "sistema" && !has && <StateBlock kind="empty" message={t("pension.emptyNoData")} />}

      {tab === "sistema" && has && (
        <>
          <div className="grid lg:grid-cols-3 gap-5">
            {/* Hero: system return */}
            <Card className="lg:col-span-1 flex flex-col items-center justify-center text-center">
              <div className="mono text-[10px] uppercase tracking-[0.16em] text-accent mb-2">
                {t("pension.cciNominal")}
              </div>
              <div className="font-display text-5xl font-extrabold text-ink mono">
                {cci != null ? fmtNum(cci, 1) : "—"}
                <span className="text-xl text-muted"> {t("pension.unitPct")}</span>
              </div>
              <div className="mt-3 text-sm text-muted">
                {t("pension.sdpNominal")}: <span className="text-body mono">{sdp != null ? `${fmtNum(sdp, 1)}%` : "—"}</span>
              </div>
            </Card>

            {/* Stats */}
            <div className="lg:col-span-2 space-y-5">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <button type="button" className="text-left" title={t("pension.drillOpen")}
                        onClick={() => setSysDrill({ kind: "indicator", code: HEADLINE_CCI, label: t("pension.cciNominal") })}>
                  <StatTile label={t("pension.cciNominal")} value={cci != null ? fmtNum(cci, 1) : "—"} unit={t("pension.unitPct")} />
                </button>
                <button type="button" className="text-left" title={t("pension.drillOpen")}
                        onClick={() => setSysDrill({ kind: "indicator", code: HEADLINE_SDP, label: t("pension.sdpNominal") })}>
                  <StatTile label={t("pension.sdpNominal")} value={sdp != null ? fmtNum(sdp, 1) : "—"} unit={t("pension.unitPct")} />
                </button>
                <button type="button" className="text-left" title={t("pension.drillOpen")}
                        onClick={() => setSysDrill({ kind: "indicator", code: HEADLINE_COMMISSIONS, label: t("pension.commissions") })}>
                  <StatTile label={t("pension.commissions")} value={commissions != null ? fmtNum(commissions, 0) : "—"} unit={t("pension.unitRdMm")} />
                </button>
                <StatTile label={t("pension.nAfp")} value={p.entity_count ?? "—"} />
              </div>
              <DispersionBars pulse={p} onPick={(slug, afp) => setSysDrill({ kind: "dimension", slug, afp })} />
            </div>
          </div>

          <div className="mt-5">
            <AiInsightCard
              title={t("pension.insightTitle")}
              subtitle={t("pension.insightSubtitle", { period: p.period ?? "" })}
              depsKey={`${p.period ?? "pension"}:${audience}`}
              fetcher={() => getPensionInsight(audience)}
              deepFetcher={(deep) => getPensionInsight(audience, deep)}
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
      )}

      {sysDrill?.kind === "indicator" && (
        <PensionDrillDrawer
          eyebrow={t("pension.eyebrow")}
          title={sysDrill.label}
          depsKey={`ind:${sysDrill.code}`}
          fetcher={(withAi, aud, deep) => getPensionIndicator(sysDrill.code, withAi, aud, deep)}
          onClose={() => setSysDrill(null)}
          renderDetail={(data) => (
            <>
              <div>
                <div className="text-3xl font-semibold text-ink mono tabular-nums">
                  {data.unit === "%" ? `${fmtNum(data.latest.value, 1)}%` : fmtNum(data.latest.value, data.latest.value >= 1000 ? 0 : 1)}
                  {data.unit && data.unit !== "%" && <span className="ml-1 text-base text-muted">{data.unit}</span>}
                </div>
                <div className="text-xs text-muted mt-1 mono">{data.latest.period}</div>
              </div>
              {data.trend.length > 1 && (
                <section>
                  <div className="mb-2 text-sm font-medium text-ink">{t("pension.drillTrend")}</div>
                  <PensionTrend points={data.trend} unit={data.unit} />
                </section>
              )}
            </>
          )}
        />
      )}

      {sysDrill?.kind === "dimension" && (
        <PensionDrillDrawer
          eyebrow={`${sysDrill.afp} · ${p.period ?? ""}`}
          title={t("pension.rentabilidadDim")}
          depsKey={`dim:${sysDrill.slug}:rentabilidad`}
          fetcher={(withAi, aud, deep) => getPensionDimension(sysDrill.slug, "rentabilidad", withAi, aud, deep)}
          shouldFetchAi={(data) => data.dimension?.present === true}
          onClose={() => setSysDrill(null)}
          renderDetail={(data) => (
            <>
              <div>
                <div className="text-3xl font-semibold text-ink mono tabular-nums">
                  {data.dimension.raw != null ? `${fmtNum(data.dimension.raw, 2)}%` : "—"}
                </div>
                <div className="text-xs text-muted mt-1">
                  {t("pension.drillRelScore")}: <span className="mono text-body">{data.dimension.present ? fmtNum(data.dimension.score, 1) : "—"}</span>
                </div>
              </div>
              {data.trend.length > 1 && (
                <section>
                  <div className="mb-2 text-sm font-medium text-ink">{t("pension.drillTrend")}</div>
                  <PensionTrend points={data.trend} unit="%" />
                </section>
              )}
              <section>
                <div className="mb-2 text-sm font-medium text-ink">{t("pension.drillPeers")}</div>
                <PeerBars peers={data.peers} focusAfp={data.afp} unit="%" />
              </section>
            </>
          )}
        />
      )}
    </div>
  );
}

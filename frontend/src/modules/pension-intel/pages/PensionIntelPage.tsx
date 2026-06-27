import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { PiggyBank } from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  StatTile,
  StateBlock,
  LoadingGrid,
  Chip,
} from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import { AudienceTabs } from "@/shared/ui/AudienceTabs";
import { useAudiencePref } from "@/shared/lib/useAudiencePref";
import {
  getPensionPulse,
  getPensionInsight,
  pulseHasData,
  PENSION_AUDIENCES,
  HEADLINE_CCI,
  HEADLINE_SDP,
  HEADLINE_COMMISSIONS,
  PensionPulse,
} from "../api";

type Status = "loading" | "error" | "ready";

/** Per-AFP rentabilidad as horizontal bars (leader → laggard), tokens only. */
function DispersionBars({ pulse }: { pulse: PensionPulse }) {
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
      <div className="mt-3 space-y-2">
        {ranking.map((r, i) => {
          const pct = max > 0 ? (r.value / max) * 100 : 0;
          const isLeader = i === 0;
          const isLaggard = i === ranking.length - 1 && ranking.length > 1;
          return (
            <div key={r.slug} className="flex items-center gap-3">
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
              <div className="w-20 shrink-0">
                {isLeader && <Chip tone="ok">{t("pension.leader")}</Chip>}
                {isLaggard && <Chip tone="warn">{t("pension.laggard")}</Chip>}
              </div>
            </div>
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

      {!has && <StateBlock kind="empty" message={t("pension.emptyNoData")} />}

      {has && (
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
                <StatTile label={t("pension.cciNominal")} value={cci != null ? fmtNum(cci, 1) : "—"} unit={t("pension.unitPct")} />
                <StatTile label={t("pension.sdpNominal")} value={sdp != null ? fmtNum(sdp, 1) : "—"} unit={t("pension.unitPct")} />
                <StatTile label={t("pension.commissions")} value={commissions != null ? fmtNum(commissions, 0) : "—"} unit={t("pension.unitRdMm")} />
                <StatTile label={t("pension.nAfp")} value={p.entity_count ?? "—"} />
              </div>
              <DispersionBars pulse={p} />
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
    </div>
  );
}

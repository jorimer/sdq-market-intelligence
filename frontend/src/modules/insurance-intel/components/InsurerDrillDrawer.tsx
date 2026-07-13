import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { StateBlock, Skeleton, Chip, BandBadge } from "@/shared/ui/primitives";
import { InsightDrawerShell } from "@/shared/ui/InsightDrawerShell";
import { DimensionBreakdown, DimensionRow } from "@/shared/ui/DimensionBreakdown";
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import { AudienceTabs } from "@/shared/ui/AudienceTabs";
import { useAudiencePref } from "@/shared/lib/useAudiencePref";
import { fmtNum, fmtPct } from "@/shared/lib/format";
import { Band, Tone } from "@/shared/lib/bands";
import {
  getInsuranceEntityDetail,
  getArsEntityDetail,
  getInsuranceEntityInsight,
  INSURANCE_AUDIENCES,
  InsuranceDetail,
} from "../api";

type Status = "loading" | "error" | "ready";

function bandToBand(band: string | null): Band {
  const tone: Tone =
    band === "Sólida" ? "ok"
    : band === "Adecuada" ? "accent"
    : band === "En vigilancia" ? "warn"
    : band === "Frágil" ? "alert"
    : "muted";
  return { label: band ?? "—", tone };
}

/** Right-side drill-down for one insurer (ISF) or ARS (ISARS): deterministic
 * dimension breakdown with per-dimension provenance + (insurers only) the
 * two-phase Cerebro entity insight — the canonical axis pattern. */
export function InsurerDrillDrawer({
  slug, name, kind, onClose,
}: { slug: string; name: string; kind: "insurer" | "ars"; onClose: () => void }) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<Status>("loading");
  const [detail, setDetail] = useState<InsuranceDetail | null>(null);
  const [audience, setAudience] = useAudiencePref("sdq.insurance.audience", INSURANCE_AUDIENCES);

  useEffect(() => {
    let alive = true;
    setStatus("loading");
    const fetcher = kind === "ars" ? getArsEntityDetail : getInsuranceEntityDetail;
    fetcher(slug)
      .then((d) => { if (alive) { setDetail(d); setStatus("ready"); } })
      .catch(() => { if (alive) setStatus("error"); });
    return () => { alive = false; };
  }, [slug, kind]);

  const rows: DimensionRow[] = (detail?.dimensions ?? []).map((d) => ({
    key: d.key,
    label: d.label,
    score: d.score ?? 0,
    weight: d.weight,
    contribution: (d.score ?? 0) * d.weight,
    // Procedencia por dimensión: el ISF/ISARS corre 100% sobre dato real
    // (estados auditados / BDFINAC); una dimensión ausente se marca "sin dato".
    tag: d.present
      ? { text: t("insurance.dimReal"), ok: true }
      : { text: t("insurance.dimMissing") },
  }));

  return (
    <InsightDrawerShell
      eyebrow={kind === "ars" ? t("insurance.drillEyebrowArs") : t("insurance.drillEyebrow")}
      title={name}
      onClose={onClose}
    >
      {status === "loading" && (
        <div className="space-y-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      )}
      {status === "error" && <StateBlock kind="error" message={t("insurance.drillError")} />}
      {status === "ready" && detail && !detail.found && (
        <StateBlock kind="empty" message={detail.note ?? t("insurance.drillEmpty")} />
      )}
      {status === "ready" && detail && detail.found && (
        <>
          <div className="flex items-center gap-3 flex-wrap">
            <span className="font-display text-3xl font-extrabold text-ink mono">
              {fmtNum(detail.overall_score, 1)}
            </span>
            <BandBadge band={bandToBand(detail.band)} />
            {detail.coverage != null && (
              <Chip tone="muted">
                {t("insurance.coverageChip", { pct: fmtPct(detail.coverage * 100, 0) })}
              </Chip>
            )}
          </div>

          <section>
            <h3 className="text-sm font-medium text-ink mb-3">{t("insurance.dimTitle")}</h3>
            <DimensionBreakdown rows={rows} />
          </section>

          {kind === "insurer" && (
            <AiInsightCard
              title={t("insurance.drillAiTitle")}
              depsKey={`${slug}:${audience}`}
              fetcher={() => getInsuranceEntityInsight(slug, audience)}
              deepFetcher={(deep) => getInsuranceEntityInsight(slug, audience, deep)}
              actions={
                <AudienceTabs
                  value={audience}
                  onChange={setAudience}
                  options={INSURANCE_AUDIENCES}
                  labelPrefix="insurance.audience"
                  ariaLabelKey="insurance.audienceLabel"
                />
              }
            />
          )}
        </>
      )}
    </InsightDrawerShell>
  );
}

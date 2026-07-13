import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { PiggyBank, Landmark, Info, ChevronRight } from "lucide-react";
import {
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
  getPensionCartera,
  getPensionCarteraInsight,
  getPensionCarteraHolding,
  PENSION_AUDIENCES,
  PensionCartera,
  PensionHolding,
} from "../api";
import { PensionDrillDrawer } from "./PensionDrillDrawer";

type Status = "loading" | "error" | "ready";

/** RD$ amount → millions (the platform's RD$ MM convention). */
const toMM = (v: number | null | undefined): string => (v != null ? fmtNum(v / 1e6, 0) : "—");

/** Honest banner: it's a quarterly snapshot from the bulletin, not a series. */
function SnapshotNote() {
  const { t } = useTranslation();
  return (
    <div className="flex items-start gap-2 rounded-[10px] bg-surface2 p-3 text-sm text-muted">
      <Info size={16} className="mt-0.5 shrink-0 text-accent" />
      <span>{t("pension.carteraNote")}</span>
    </div>
  );
}

/** Top-level composition (sub-sector rollups + sovereign leaves) as horizontal bars. */
function CompositionBars({ cartera, onPick }: { cartera: PensionCartera; onPick: (slug: string) => void }) {
  const { t } = useTranslation();
  const total = cartera.total ?? 0;
  // Top-level rows partition the total: sub-sector headers + standalone leaves (Hacienda/BCRD).
  const top = cartera.holdings
    .filter((h) => (h.is_subtotal || h.sub_sector == null) && h.amount != null)
    .sort((a, b) => (b.amount ?? 0) - (a.amount ?? 0));
  const max = top.length ? Math.max(...top.map((h) => h.amount ?? 0)) : 0;

  return (
    <Card>
      <CardHead
        icon={PiggyBank}
        title={t("pension.carteraCompTitle")}
        subtitle={t("pension.carteraCompSubtitle", { period: cartera.period ?? "—" })}
        right={<Chip tone="muted">{t("pension.carteraTotal")}: {toMM(total)} {t("pension.unitRdMm")}</Chip>}
      />
      <div className="mt-3 space-y-2">
        {top.map((h) => {
          const w = max > 0 ? ((h.amount ?? 0) / max) * 100 : 0;
          const sovereign = h.macro_class === "deuda_publica" || h.macro_class === "bcrd";
          return (
            <button
              key={h.issuer}
              type="button"
              onClick={() => onPick(h.issuer_slug)}
              className="flex w-full items-center gap-3 rounded-[8px] px-1.5 py-1 text-left transition-colors hover:bg-surface2/60"
              title={t("pension.drillOpen")}
            >
              <div className="w-40 shrink-0 truncate text-sm text-body" title={h.issuer}>
                {h.issuer}
              </div>
              <div className="relative h-5 flex-1 min-w-0 rounded-[6px] bg-surface2">
                <div
                  className={"absolute inset-y-0 left-0 rounded-[6px] " + (sovereign ? "bg-c3" : "bg-accent")}
                  style={{ width: `${w}%` }}
                />
              </div>
              <div className="w-24 shrink-0 text-right font-display text-sm font-extrabold text-ink mono">
                {toMM(h.amount)}
              </div>
              <div className="w-14 shrink-0 text-right text-sm text-muted mono">
                {h.pct != null ? `${fmtNum(h.pct, 1)}%` : "—"}
              </div>
              <ChevronRight size={14} className="shrink-0 text-faint" />
            </button>
          );
        })}
      </div>
    </Card>
  );
}

/** Largest individual issuers (leaves) — the granular exposure behind the rollups. */
function TopIssuers({ holdings, onPick }: { holdings: PensionHolding[]; onPick: (slug: string) => void }) {
  const { t } = useTranslation();
  const leaves = holdings
    .filter((h) => !h.is_subtotal && h.amount != null)
    .sort((a, b) => (b.amount ?? 0) - (a.amount ?? 0))
    .slice(0, 10);

  return (
    <Card>
      <CardHead icon={Landmark} title={t("pension.carteraTopTitle")} subtitle={t("pension.carteraTopSubtitle")} />
      <div className="mt-3 divide-y divide-line">
        {leaves.map((h) => (
          <button
            key={h.issuer_slug}
            type="button"
            onClick={() => onPick(h.issuer_slug)}
            className="flex w-full items-center gap-3 py-2.5 text-left transition-colors hover:bg-surface2/50"
            title={t("pension.drillOpen")}
          >
            <div className="flex-1 min-w-0">
              <div className="truncate text-sm text-body" title={h.issuer}>{h.issuer}</div>
              {h.sub_sector && <div className="truncate text-[11px] text-muted">{h.sub_sector}</div>}
            </div>
            {h.macro_class === "deuda_publica" && <Chip tone="accent">{t("pension.carteraSovereign")}</Chip>}
            {h.macro_class === "bcrd" && <Chip tone="accent">{t("pension.carteraBcrd")}</Chip>}
            <div className="w-24 shrink-0 text-right font-display text-sm font-extrabold text-ink mono">
              {toMM(h.amount)}
            </div>
            <div className="w-14 shrink-0 text-right text-sm text-muted mono">
              {h.pct != null ? `${fmtNum(h.pct, 1)}%` : "—"}
            </div>
            <ChevronRight size={14} className="shrink-0 text-faint" />
          </button>
        ))}
      </div>
    </Card>
  );
}

export function CarteraTab() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<Status>("loading");
  const [cartera, setCartera] = useState<PensionCartera | null>(null);
  const [drillSlug, setDrillSlug] = useState<string | null>(null);
  const [audience, setAudience] = useAudiencePref("sdq.pension.audience", PENSION_AUDIENCES);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      setCartera(await getPensionCartera());
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
    return <StateBlock kind="error" message={t("pension.carteraError")} action={<button onClick={load} className="btn btn-ghost">{t("common_retry")}</button>} />;
  if (!cartera?.found) return <StateBlock kind="empty" message={t("pension.carteraEmpty")} />;

  const c = cartera;
  const s = c.summary;
  return (
    <div className="space-y-5">
      <SnapshotNote />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatTile label={t("pension.carteraTotal")} value={toMM(c.total)} unit={t("pension.unitRdMm")} />
        <StatTile label={t("pension.carteraPublicDebt")} value={s?.public_debt_pct != null ? fmtNum(s.public_debt_pct, 1) : "—"} unit={t("pension.unitPct")} />
        <StatTile label={t("pension.carteraBcrd")} value={s?.bcrd_pct != null ? fmtNum(s.bcrd_pct, 1) : "—"} unit={t("pension.unitPct")} />
        <StatTile label={t("pension.carteraIssuers")} value={s?.issuer_count ?? "—"} />
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        <CompositionBars cartera={c} onPick={setDrillSlug} />
        <TopIssuers holdings={c.holdings} onPick={setDrillSlug} />
      </div>

      {drillSlug && (() => {
        const h = c.holdings.find((x) => x.issuer_slug === drillSlug);
        return (
          <PensionDrillDrawer
            eyebrow={`${t("pension.carteraTotal")} · ${c.period ?? ""}`}
            title={h?.issuer ?? drillSlug}
            depsKey={`cartera:${c.period ?? ""}:${drillSlug}`}
            fetcher={(withAi, aud, deep) => getPensionCarteraHolding(drillSlug, withAi, aud, deep, c.period ?? undefined)}
            onClose={() => setDrillSlug(null)}
            renderDetail={(data) => {
              const hd = data.holding;
              const sovereign = hd.macro_class === "deuda_publica" || hd.macro_class === "bcrd";
              return (
                <div className="flex items-end justify-between gap-4">
                  <div className="min-w-0">
                    {hd.sub_sector && <div className="text-xs text-muted mb-1 truncate">{hd.sub_sector}</div>}
                    <div className="text-3xl font-semibold text-ink mono tabular-nums">{toMM(hd.amount)} <span className="text-base text-muted">{t("pension.unitRdMm")}</span></div>
                    <div className="text-xs text-muted mt-1">{hd.pct != null ? `${fmtNum(hd.pct, 2)}% ${t("pension.carteraOfPortfolio")}` : "—"}</div>
                  </div>
                  {hd.macro_class === "deuda_publica" && <Chip tone="accent">{t("pension.carteraSovereign")}</Chip>}
                  {hd.macro_class === "bcrd" && <Chip tone="accent">{t("pension.carteraBcrd")}</Chip>}
                  {!sovereign && hd.is_subtotal && <Chip tone="muted">{t("pension.carteraSubSector")}</Chip>}
                </div>
              );
            }}
          />
        );
      })()}

      <AiInsightCard
        title={t("pension.carteraInsightTitle")}
        subtitle={t("pension.carteraInsightSubtitle", { period: c.period ?? "" })}
        depsKey={`cartera:${c.period ?? ""}:${audience}`}
        fetcher={() => getPensionCarteraInsight(audience)}
        deepFetcher={(deep) => getPensionCarteraInsight(audience, deep)}
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
  );
}

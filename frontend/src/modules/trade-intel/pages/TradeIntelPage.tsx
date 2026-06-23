import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Boxes } from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  Gauge,
  BandBadge,
  StatTile,
  StateBlock,
  LoadingGrid,
  Tabs,
} from "@/shared/ui/primitives";
import { bandFor } from "@/shared/lib/bands";
import { fmtNum, fmtPct } from "@/shared/lib/format";
import { Treemap } from "@/shared/charts/Treemap";
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import { AudienceTabs } from "@/shared/ui/AudienceTabs";
import { useAudiencePref } from "@/shared/lib/useAudiencePref";
import { getTradeScore, getTradeInsight, TRADE_AUDIENCES, TradeScore } from "../api";
import { ValidationTab } from "../components/ValidationTab";
import { PartnersTab } from "../components/PartnersTab";

type Status = "loading" | "error" | "ready";

export function TradeIntelPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<Status>("loading");
  const [score, setScore] = useState<TradeScore | null>(null);
  const [tab, setTab] = useState("panorama");
  const [audience, setAudience] = useAudiencePref("sdq.trade.audience", TRADE_AUDIENCES);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      setScore(await getTradeScore());
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const head = (
    <PageHead
      eyebrow={t("trade.eyebrow")}
      title={t("trade.title")}
      sub={t("trade.subDefault")}
    />
  );

  if (status === "loading") return <div>{head}<LoadingGrid /></div>;
  if (status === "error")
    return (
      <div>
        {head}
        <StateBlock
          kind="error"
          message={t("trade.errorLoad")}
          action={<button onClick={load} className="btn btn-ghost">{t("common_retry")}</button>}
        />
      </div>
    );

  const s = score!;
  const band = s.has_score ? bandFor(s.resilience_score, t) : null;

  return (
    <div>
      <PageHead
        eyebrow={t("trade.eyebrow")}
        title={t("trade.title")}
        sub={s.has_score ? t("trade.subScored", { period: s.period ?? "—" }) : t("trade.subDefault")}
      />

      <Card className="mb-5">
        <Tabs
          tabs={[
            { id: "panorama", label: t("trade.tabPanorama") },
            { id: "socios", label: t("trade.tabPartners") },
            { id: "validacion", label: t("trade.tabValidation") },
          ]}
          active={tab}
          onChange={setTab}
        />
      </Card>

      {tab === "socios" && <PartnersTab />}

      {tab === "validacion" && <ValidationTab />}

      {tab === "panorama" && !s.has_score && (
        <StateBlock kind="empty" message={t("trade.emptyNoData")} />
      )}

      {tab === "panorama" && s.has_score && band && (
        <>
          <div className="grid lg:grid-cols-3 gap-5">
            {/* Hero */}
            <Card className="lg:col-span-1 flex flex-col items-center text-center">
              <div className="mono text-[10px] uppercase tracking-[0.16em] text-accent mb-2">
                {t("trade.resilienceIndex")}
              </div>
              <Gauge score={s.resilience_score} band={band} />
              <div className="mt-3">
                <BandBadge band={band} />
              </div>
              <div className="grid grid-cols-2 gap-3 w-full mt-5">
                <div className="rounded-[10px] bg-surface2 p-3">
                  <div className="text-[11px] text-muted">{t("trade.diversification")}</div>
                  <div className="font-display text-lg font-extrabold text-ink mono mt-0.5">
                    {fmtNum(s.export_diversification, 1)}
                  </div>
                </div>
                <div className="rounded-[10px] bg-surface2 p-3">
                  <div className="text-[11px] text-muted">{t("trade.importDep")}</div>
                  <div className="font-display text-lg font-extrabold text-ink mono mt-0.5">
                    {s.import_dependency != null ? fmtPct(s.import_dependency * 100, 0) : "—"}
                  </div>
                </div>
              </div>
            </Card>

            {/* Concentration */}
            <div className="lg:col-span-2 space-y-5">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <StatTile label={t("trade.hhiExports")} value={fmtNum(s.hhi_exports, 3)} />
                <StatTile label={t("trade.chaptersExport")} value={s.n_products_export ?? "—"} />
                <StatTile label={t("trade.totalExports")} value={fmtNum(s.total_exports, 0)} unit={t("trade.unitMusd")} />
                <StatTile label={t("trade.totalImports")} value={fmtNum(s.total_imports, 0)} unit={t("trade.unitMusd")} />
              </div>

              <Card>
                <CardHead
                  icon={Boxes}
                  title={t("trade.concentrationTitle")}
                  subtitle={t("trade.concentrationSubtitle")}
                />
                <Treemap
                  items={s.top_export_products.map((p) => ({
                    label: p.product,
                    value: p.value,
                    share: p.share,
                  }))}
                />
              </Card>
            </div>
          </div>

          <div className="mt-5">
            <AiInsightCard
              title={t("trade.insightTitle")}
              subtitle={t("trade.insightSubtitle", { period: s.period ?? "" })}
              depsKey={`${s.period ?? "trade"}:${audience}`}
              fetcher={() => getTradeInsight(audience)}
              deepFetcher={(deep) => getTradeInsight(audience, deep)}
              actions={
                <AudienceTabs
                  value={audience}
                  onChange={setAudience}
                  options={TRADE_AUDIENCES}
                  labelPrefix="trade.audience"
                  ariaLabelKey="trade.audienceLabel"
                />
              }
            />
          </div>
        </>
      )}
    </div>
  );
}

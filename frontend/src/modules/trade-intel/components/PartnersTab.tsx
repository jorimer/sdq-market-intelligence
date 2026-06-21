import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Globe } from "lucide-react";
import { Card, CardHead, StatTile, StateBlock } from "@/shared/ui/primitives";
import { fmtNum, fmtPct } from "@/shared/lib/format";
import { getTradePartners, TradePartners, PartnerBlock } from "../api";

function Block({ title, b, t }: { title: string; b: PartnerBlock; t: TFunction }) {
  const max = Math.max(0.0001, ...b.top.map((x) => x.share));
  return (
    <Card>
      <CardHead icon={Globe} title={title} subtitle={t("trade.blockSubtitle", { n: b.n_partners })} />
      <div className="grid grid-cols-3 gap-3 mb-4">
        <StatTile label={t("trade.hhiPartners")} value={fmtNum(b.hhi, 3)} />
        <StatTile label={t("trade.diversification")} value={fmtNum(b.diversification, 1)} />
        <StatTile label={t("trade.total")} value={fmtNum(b.total, 0)} unit={t("trade.unitMusd")} />
      </div>
      <div className="space-y-2">
        {b.top.map((row) => (
          <div key={row.partner} className="flex items-center gap-3">
            <span className="w-28 shrink-0 text-xs text-ink truncate">{row.partner}</span>
            <div className="flex-1 h-3 rounded-full bg-surface2 overflow-hidden">
              <div className="h-full rounded-full bg-accent" style={{ width: `${(row.share / max) * 100}%` }} />
            </div>
            <span className="w-24 shrink-0 text-right mono text-xs text-body tabular-nums">
              {fmtPct(row.share * 100, 1)} <span className="text-faint">· {fmtNum(row.value, 0)}M</span>
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

export function PartnersTab() {
  const { t } = useTranslation();
  const [data, setData] = useState<TradePartners | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");

  useEffect(() => {
    getTradePartners()
      .then((d) => {
        setData(d);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, []);

  if (status === "loading") return <StateBlock kind="loading" message={t("trade.partnersLoading")} />;
  if (status === "error") return <StateBlock kind="error" message={t("trade.partnersError")} />;
  if (!data?.has_data || !data.export || !data.import) {
    return (
      <StateBlock kind="empty" message={t("trade.partnersEmpty")} />
    );
  }

  return (
    <div>
      <p className="mb-4 text-xs text-muted">
        {t("trade.partnersIntro", { period: data.period, source: data.source })}
      </p>
      <div className="grid lg:grid-cols-2 gap-5">
        <Block title={t("trade.exportsByPartner")} b={data.export} t={t} />
        <Block title={t("trade.importsByPartner")} b={data.import} t={t} />
      </div>
    </div>
  );
}

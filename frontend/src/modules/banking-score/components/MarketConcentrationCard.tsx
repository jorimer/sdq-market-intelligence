import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Network } from "lucide-react";
import { Card, CardHead, Skeleton, StateBlock } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { getMarketConcentration, MarketConcentration } from "../api";

const METRICS = [
  { value: "activos", key: "mcMetricActivos" },
  { value: "depositos", key: "mcMetricDepositos" },
  { value: "cartera", key: "mcMetricCartera" },
];

/** HHI reading (US DoJ thresholds, ×10000 scale). */
function hhiLabel(hhi: number, t: TFunction): string {
  if (hhi < 1500) return t("banking.mcHhiNotConc");
  if (hhi < 2500) return t("banking.mcHhiModerate");
  return t("banking.mcHhiHigh");
}

function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="text-xs text-muted">{label}</div>
      <div className="mono text-2xl font-semibold text-ink tabular-nums leading-tight">{value}</div>
      {sub && <div className="text-[11px] text-faint">{sub}</div>}
    </div>
  );
}

/** System-level market concentration of the EIF (CR5/CR10/HHI). Not a per-bank input. */
export function MarketConcentrationCard() {
  const { t } = useTranslation();
  const [metric, setMetric] = useState("activos");
  const [data, setData] = useState<MarketConcentration | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    getMarketConcentration(metric)
      .then((d) => active && setData(d))
      .catch(() => active && setError(true))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [metric]);

  return (
    <Card className="mt-5">
      <CardHead
        icon={Network}
        title={t("banking.mcTitle")}
        subtitle={t("banking.mcSubtitle")}
        right={
          <select
            value={metric}
            onChange={(e) => setMetric(e.target.value)}
            className="field !w-auto !py-1 text-xs"
            title={t("banking.mcMetricSelect")}
          >
            {METRICS.map((m) => (
              <option key={m.value} value={m.value}>{t(`banking.${m.key}`)}</option>
            ))}
          </select>
        }
      />

      {loading ? (
        <div className="space-y-2"><Skeleton className="h-8 w-2/3" /><Skeleton className="h-24 w-full" /></div>
      ) : error || !data?.available ? (
        <StateBlock kind="empty" message={t("banking.mcEmpty")} />
      ) : (
        <div>
          <div className="grid grid-cols-3 gap-4 mb-4">
            <Metric label="CR10" value={`${fmtNum(data.cr10, 1)}%`} sub={t("banking.mcCr10Sub", { n: data.n_entities })} />
            <Metric label="CR5" value={`${fmtNum(data.cr5, 1)}%`} sub={t("banking.mcCr5Sub")} />
            <Metric label="HHI" value={fmtNum(data.hhi, 0)} sub={hhiLabel(data.hhi ?? 0, t)} />
          </div>
          <p className="text-xs text-muted mb-3">
            {t("banking.mcDescPrefix", { label: data.metric_label })}<span className="mono text-body">{data.period_end}</span>{t("banking.mcDescSuffix")}
          </p>
          <div className="space-y-1.5">
            {data.top10?.map((e, i) => (
              <div key={e.name} className="flex items-center gap-3">
                <span className="w-5 shrink-0 mono text-xs text-faint">{i + 1}</span>
                <span className="w-44 shrink-0 text-sm text-body truncate" title={e.name}>{e.name}</span>
                <div className="flex-1 h-2 rounded-full bg-surface2 overflow-hidden">
                  <div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(e.share, 100)}%` }} />
                </div>
                <span className="w-12 shrink-0 text-right mono text-xs text-ink tabular-nums">{fmtNum(e.share, 1)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

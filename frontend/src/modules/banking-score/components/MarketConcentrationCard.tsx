import { useEffect, useState } from "react";
import { Network } from "lucide-react";
import { Card, CardHead, Skeleton, StateBlock } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { getMarketConcentration, MarketConcentration } from "../api";

const METRICS = [
  { value: "activos", label: "Activos" },
  { value: "depositos", label: "Depósitos" },
  { value: "cartera", label: "Cartera" },
];

/** HHI reading (US DoJ thresholds, ×10000 scale). */
function hhiLabel(hhi: number): string {
  if (hhi < 1500) return "mercado no concentrado";
  if (hhi < 2500) return "concentración moderada";
  return "mercado altamente concentrado";
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
        title="Concentración de mercado (EIF)"
        subtitle="CR10 · estructura del sistema, no input del rating"
        right={
          <select
            value={metric}
            onChange={(e) => setMetric(e.target.value)}
            className="field !w-auto !py-1 text-xs"
            title="Métrica"
          >
            {METRICS.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
        }
      />

      {loading ? (
        <div className="space-y-2"><Skeleton className="h-8 w-2/3" /><Skeleton className="h-24 w-full" /></div>
      ) : error || !data?.available ? (
        <StateBlock kind="empty" message="No hay datos suficientes para calcular la concentración." />
      ) : (
        <div>
          <div className="grid grid-cols-3 gap-4 mb-4">
            <Metric label="CR10" value={`${fmtNum(data.cr10, 1)}%`} sub={`10 mayores de ${data.n_entities}`} />
            <Metric label="CR5" value={`${fmtNum(data.cr5, 1)}%`} sub="5 mayores" />
            <Metric label="HHI" value={fmtNum(data.hhi, 0)} sub={hhiLabel(data.hhi ?? 0)} />
          </div>
          <p className="text-xs text-muted mb-3">
            {data.metric_label} de las EIF · período <span className="mono text-body">{data.period_end}</span>.
            CR10 = activos de las 10 mayores / activos del sistema.
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

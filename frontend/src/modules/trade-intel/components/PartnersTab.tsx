import { useEffect, useState } from "react";
import { Globe } from "lucide-react";
import { Card, CardHead, StatTile, StateBlock } from "@/shared/ui/primitives";
import { fmtNum, fmtPct } from "@/shared/lib/format";
import { getTradePartners, TradePartners, PartnerBlock } from "../api";

function Block({ title, b }: { title: string; b: PartnerBlock }) {
  const max = Math.max(0.0001, ...b.top.map((t) => t.share));
  return (
    <Card>
      <CardHead icon={Globe} title={title} subtitle={`${b.n_partners} socios · diversificación > volumen`} />
      <div className="grid grid-cols-3 gap-3 mb-4">
        <StatTile label="HHI socios" value={fmtNum(b.hhi, 3)} />
        <StatTile label="Diversificación" value={fmtNum(b.diversification, 1)} />
        <StatTile label="Total" value={fmtNum(b.total, 0)} unit="M US$" />
      </div>
      <div className="space-y-2">
        {b.top.map((t) => (
          <div key={t.partner} className="flex items-center gap-3">
            <span className="w-28 shrink-0 text-xs text-ink truncate">{t.partner}</span>
            <div className="flex-1 h-3 rounded-full bg-surface2 overflow-hidden">
              <div className="h-full rounded-full bg-accent" style={{ width: `${(t.share / max) * 100}%` }} />
            </div>
            <span className="w-24 shrink-0 text-right mono text-xs text-body tabular-nums">
              {fmtPct(t.share * 100, 1)} <span className="text-faint">· {fmtNum(t.value, 0)}M</span>
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

export function PartnersTab() {
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

  if (status === "loading") return <StateBlock kind="loading" message="Cargando socios comerciales…" />;
  if (status === "error") return <StateBlock kind="error" message="No se pudieron cargar los socios." />;
  if (!data?.has_data || !data.export || !data.import) {
    return (
      <StateBlock kind="empty" message="Aún no hay datos de socios comerciales." />
    );
  }

  return (
    <div>
      <p className="mb-4 text-xs text-muted">
        Concentración geográfica del comercio de RD por país socio · período {data.period} · {data.source}.
        El detalle por país que el Power BI de la DGA no exporta.
      </p>
      <div className="grid lg:grid-cols-2 gap-5">
        <Block title="Exportaciones por socio" b={data.export} />
        <Block title="Importaciones por socio" b={data.import} />
      </div>
    </div>
  );
}

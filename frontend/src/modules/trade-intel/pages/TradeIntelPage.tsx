import { useEffect, useState, useCallback } from "react";
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
} from "@/shared/ui/primitives";
import { bandFor } from "@/shared/lib/bands";
import { fmtNum, fmtPct } from "@/shared/lib/format";
import { Treemap } from "@/shared/charts/Treemap";
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import { getTradeScore, getTradeInsight, TradeScore } from "../api";

type Status = "loading" | "error" | "ready";

export function TradeIntelPage() {
  const [status, setStatus] = useState<Status>("loading");
  const [score, setScore] = useState<TradeScore | null>(null);

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
      eyebrow="DGA · Aduanas"
      title="Comercio exterior"
      sub="Resiliencia comercial: diversificación y dependencia, no volumen. Datos de la DGA (Aduanas), por capítulo arancelario."
    />
  );

  if (status === "loading") return <div>{head}<LoadingGrid /></div>;
  if (status === "error")
    return (
      <div>
        {head}
        <StateBlock
          kind="error"
          message="No se pudo cargar el índice de comercio. Reintenta."
          action={<button onClick={load} className="btn btn-ghost">Reintentar</button>}
        />
      </div>
    );

  const s = score!;
  if (!s.has_score)
    return (
      <div>
        {head}
        <StateBlock
          kind="empty"
          message="Aún no hay datos de comercio. Corre la operación «Sincronizar comercio (Aduanas/DGA)» en la Consola de Operación para ingerir las estadísticas de comercio exterior."
        />
      </div>
    );

  const band = bandFor(s.resilience_score);

  return (
    <div>
      <PageHead
        eyebrow="DGA · Aduanas"
        title="Comercio exterior"
        sub={`Resiliencia comercial por capítulo arancelario (DGA). Período ${s.period ?? "—"}.`}
      />

      <div className="grid lg:grid-cols-3 gap-5">
        {/* Hero */}
        <Card className="lg:col-span-1 flex flex-col items-center text-center">
          <div className="mono text-[10px] uppercase tracking-[0.16em] text-accent mb-2">
            Índice de resiliencia
          </div>
          <Gauge score={s.resilience_score} band={band} />
          <div className="mt-3">
            <BandBadge band={band} />
          </div>
          <div className="grid grid-cols-2 gap-3 w-full mt-5">
            <div className="rounded-[10px] bg-surface2 p-3">
              <div className="text-[11px] text-muted">Diversificación</div>
              <div className="font-display text-lg font-extrabold text-ink mono mt-0.5">
                {fmtNum(s.export_diversification, 1)}
              </div>
            </div>
            <div className="rounded-[10px] bg-surface2 p-3">
              <div className="text-[11px] text-muted">Dep. importaciones</div>
              <div className="font-display text-lg font-extrabold text-ink mono mt-0.5">
                {s.import_dependency != null ? fmtPct(s.import_dependency * 100, 0) : "—"}
              </div>
            </div>
          </div>
        </Card>

        {/* Concentration */}
        <div className="lg:col-span-2 space-y-5">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatTile label="HHI exportaciones" value={fmtNum(s.hhi_exports, 3)} />
            <StatTile label="Capítulos export." value={s.n_products_export ?? "—"} />
            <StatTile label="Export. total" value={fmtNum(s.total_exports, 0)} unit="M US$" />
            <StatTile label="Import. total" value={fmtNum(s.total_imports, 0)} unit="M US$" />
          </div>

          <Card>
            <CardHead
              icon={Boxes}
              title="Concentración de exportaciones"
              subtitle="Participación por capítulo (HHI · diversificación > volumen)"
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
          title="Perspectiva del comercio (IA)"
          subtitle={`Resiliencia, concentración y dependencia · ${s.period ?? ""} · SCQA`.trim()}
          depsKey={s.period ?? "trade"}
          fetcher={getTradeInsight}
        />
      </div>
    </div>
  );
}

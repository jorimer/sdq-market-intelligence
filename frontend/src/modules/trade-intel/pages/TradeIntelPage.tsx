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
import { useApp } from "@/shared/context/AppContext";
import { Treemap } from "@/shared/charts/Treemap";
import { scoreTrade, saveSnapshot, TradeScore } from "../api";
import { SAMPLE_FLOWS } from "../data";

type Status = "loading" | "error" | "ready";

export function TradeIntelPage() {
  const { period } = useApp();
  const [status, setStatus] = useState<Status>("loading");
  const [score, setScore] = useState<TradeScore | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      setScore(await scoreTrade(SAMPLE_FLOWS));
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
      eyebrow="BCRD · DGA"
      title="Comercio exterior"
      sub="Resiliencia comercial: diversificación y dependencia, no volumen. Datos ilustrativos."
    />
  );

  if (status === "loading") return <div>{head}<LoadingGrid /></div>;
  if (status === "error")
    return (
      <div>
        {head}
        <StateBlock
          kind="error"
          message="No se pudo calcular el índice de comercio. Reintenta."
          action={<button onClick={load} className="btn btn-ghost">Reintentar</button>}
        />
      </div>
    );

  const s = score!;
  const band = bandFor(s.resilience_score);

  const doSave = async () => {
    setSaved(null);
    try {
      await saveSnapshot(period.slice(0, 4), SAMPLE_FLOWS);
      setSaved("Snapshot guardado · evento trade.updated publicado");
    } catch {
      setSaved("No se pudo guardar el snapshot.");
    }
  };

  return (
    <div>
      <PageHead
        eyebrow="BCRD · DGA"
        title="Comercio exterior"
        sub="Resiliencia comercial: diversificación y dependencia, no volumen. Datos ilustrativos."
        right={
          <button onClick={doSave} className="btn btn-soft">
            Guardar snapshot
          </button>
        }
      />
      {saved && <div className="text-xs text-muted mb-3 -mt-3">{saved}</div>}

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
            <StatTile label="Productos export." value={s.n_products_export} />
            <StatTile label="Export. total" value={fmtNum(s.total_exports, 0)} unit="M" />
            <StatTile label="Import. total" value={fmtNum(s.total_imports, 0)} unit="M" />
          </div>

          <Card>
            <CardHead
              icon={Boxes}
              title="Concentración de exportaciones"
              subtitle="Participación por producto (HHI · diversificación > volumen)"
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
    </div>
  );
}

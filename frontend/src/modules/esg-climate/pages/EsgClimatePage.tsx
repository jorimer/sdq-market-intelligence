import { useEffect, useState, useCallback } from "react";
import { Leaf, ListOrdered, AlertTriangle } from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  Gauge,
  Chip,
  Tabs,
  StateBlock,
  LoadingGrid,
} from "@/shared/ui/primitives";
import { DimensionBreakdown, DimensionRow } from "@/shared/ui/DimensionBreakdown";
import { Band } from "@/shared/lib/bands";
import { fmtNum } from "@/shared/lib/format";
import {
  getIndicators,
  getSectorScore,
  ESGIndicator,
  ESGSectorDetail,
} from "../api";
import { SECTOR_NAMES, DIM_LABELS, MATERIALITY_TONE } from "../data";

type Status = "loading" | "error" | "ready";

// Higher score = lower exposure / better managed.
function esgBand(score: number | null | undefined): Band {
  if (score == null) return { label: "Sin dato", tone: "muted" };
  if (score >= 70) return { label: "Exposición baja", tone: "ok" };
  if (score >= 40) return { label: "Exposición moderada", tone: "warn" };
  return { label: "Exposición alta", tone: "alert" };
}

const nameOf = (key: string) => SECTOR_NAMES[key] ?? key;

export function EsgClimatePage() {
  const [status, setStatus] = useState<Status>("loading");
  const [sectors, setSectors] = useState<ESGIndicator[]>([]);
  const [detail, setDetail] = useState<ESGSectorDetail | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState("desglose");

  const loadDetail = useCallback(async (key: string) => {
    try {
      setDetail(await getSectorScore(key));
    } catch {
      setDetail(null);
    }
  }, []);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const r = await getIndicators();
      setSectors(r.indicators);
      setSelected((prev) =>
        prev && r.indicators.some((s) => s.sector_key === prev)
          ? prev
          : r.indicators[0]?.sector_key ?? null,
      );
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (status === "ready" && selected) loadDetail(selected);
  }, [selected, status, loadDetail]);

  const head = (
    <PageHead
      eyebrow="TCFD/ISSB"
      title="ESG & clima"
      sub="Exposición climática y materialidad por sector. Mayor score = menor exposición."
    />
  );

  if (status === "loading") return <div>{head}<LoadingGrid /></div>;
  if (status === "error")
    return (
      <div>
        {head}
        <StateBlock
          kind="error"
          message="No se pudo cargar la exposición ESG. Reintenta."
          action={<button onClick={load} className="btn btn-ghost">Reintentar</button>}
        />
      </div>
    );

  if (sectors.length === 0)
    return (
      <div>
        {head}
        <StateBlock
          kind="empty"
          message="Aún no hay datos ESG/clima por sector. La metodología (exposición física, transición, adaptación y gobernanza) está lista; falta una fuente sectorial real para alimentarla."
        />
      </div>
    );

  const cur = sectors.find((s) => s.sector_key === selected);
  const band = esgBand(cur?.esg_score);
  // Most exposed first (ascending score).
  const ranking = [...sectors].sort((a, b) => a.esg_score - b.esg_score);

  const dims = detail?.breakdown?.dimensions ?? {};
  const rows: DimensionRow[] = Object.entries(dims).map(([key, d]) => ({
    key,
    label: DIM_LABELS[key] ?? key,
    score: d.score,
    weight: d.weight,
    contribution: d.contribution,
  }));
  const materiality = detail?.breakdown?.materiality;

  return (
    <div>
      <PageHead
        eyebrow="TCFD/ISSB"
        title="ESG & clima"
        sub="Exposición climática y materialidad por sector. Mayor score = menor exposición."
        right={
          <select
            value={selected ?? ""}
            onChange={(e) => setSelected(e.target.value)}
            className="field !w-auto"
            title="Sector"
          >
            {sectors.map((s) => (
              <option key={s.sector_key} value={s.sector_key}>
                {nameOf(s.sector_key)}
              </option>
            ))}
          </select>
        }
      />

      <div className="grid lg:grid-cols-3 gap-5">
        {/* Hero */}
        <Card className="lg:col-span-1 flex flex-col items-center text-center">
          <div className="text-xs text-muted mb-3 w-full truncate">
            {selected ? nameOf(selected) : "—"}
          </div>
          <Gauge score={cur?.esg_score} band={band} />
          <div className="mt-3 flex items-center gap-2">
            <Chip tone={band.tone}>{band.label}</Chip>
          </div>
          {materiality && (
            <div className="mt-4 w-full rounded-[10px] bg-surface2 p-3 text-left">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-muted">Materialidad financiera</span>
                <Chip tone={MATERIALITY_TONE[materiality.level] ?? "muted"}>
                  {materiality.level}
                </Chip>
              </div>
              {materiality.greenwashing_watch && (
                <div className="flex items-center gap-1.5 text-xs text-warn mt-2">
                  <AlertTriangle size={13} />
                  Vigilancia de greenwashing
                </div>
              )}
            </div>
          )}
        </Card>

        {/* Tabs */}
        <div className="lg:col-span-2">
          <Card>
            <Tabs
              tabs={[
                { id: "desglose", label: "Desglose" },
                { id: "ranking", label: "Ranking de exposición" },
              ]}
              active={tab}
              onChange={setTab}
            />
            <div className="pt-5">
              {tab === "desglose" && (
                <>
                  <CardHead
                    icon={Leaf}
                    title="Dimensiones de exposición"
                    subtitle={`${selected ? nameOf(selected) : "—"} · mayor = mejor gestión`}
                  />
                  <DimensionBreakdown rows={rows} />
                </>
              )}

              {tab === "ranking" && (
                <>
                  <CardHead
                    icon={ListOrdered}
                    title="Ranking de exposición"
                    subtitle="Más expuestos primero"
                  />
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-muted border-b border-line">
                        <th className="py-2 px-1 font-medium">#</th>
                        <th className="py-2 px-1 font-medium">Sector</th>
                        <th className="py-2 px-1 font-medium text-right">IRC</th>
                        <th className="py-2 px-1 font-medium">Exposición</th>
                        <th className="py-2 px-1 font-medium">Materialidad</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ranking.map((s, i) => {
                        const b = esgBand(s.esg_score);
                        return (
                          <tr
                            key={s.sector_key}
                            className={`border-b border-line/60 last:border-0 ${
                              s.sector_key === selected ? "bg-accent-soft/40" : ""
                            }`}
                          >
                            <td className="py-2.5 px-1 mono text-muted">{i + 1}</td>
                            <td className="py-2.5 px-1 text-ink truncate">
                              {nameOf(s.sector_key)}
                            </td>
                            <td className="py-2.5 px-1 text-right mono font-semibold text-ink">
                              {fmtNum(s.esg_score, 1)}
                            </td>
                            <td className="py-2.5 px-1">
                              <Chip tone={b.tone}>{b.label}</Chip>
                            </td>
                            <td className="py-2.5 px-1">
                              <Chip tone={MATERIALITY_TONE[s.materiality_level] ?? "muted"}>
                                {s.materiality_level}
                              </Chip>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </>
              )}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

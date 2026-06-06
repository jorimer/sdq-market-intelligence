import { useEffect, useState, useCallback } from "react";
import { Users, ListOrdered, BarChart3 } from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  Gauge,
  BandBadge,
  StatTile,
  Tabs,
  StateBlock,
  LoadingGrid,
} from "@/shared/ui/primitives";
import { DimensionBreakdown, DimensionRow } from "@/shared/ui/DimensionBreakdown";
import { bandFor, toneVar } from "@/shared/lib/bands";
import { fmtNum } from "@/shared/lib/format";
import { useApp } from "@/shared/context/AppContext";
import {
  computeIndex,
  getDetail,
  IndexResult,
  SdgDetail,
} from "../api";
import { SAMPLE_REGIONS, REGION_NAMES, DIM_LABELS } from "../data";

type Status = "loading" | "error" | "ready";

export function SocialDevPage() {
  const { period } = useApp();
  const [status, setStatus] = useState<Status>("loading");
  const [result, setResult] = useState<IndexResult | null>(null);
  const [detail, setDetail] = useState<SdgDetail | null>(null);
  const [selected, setSelected] = useState("nacional");
  const [tab, setTab] = useState("distribucion");

  const loadDetail = useCallback(async (key: string) => {
    try {
      setDetail(await getDetail(key));
    } catch {
      setDetail(null);
    }
  }, []);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const r = await computeIndex(period, SAMPLE_REGIONS);
      setResult(r);
      await loadDetail(selected);
      setStatus("ready");
    } catch {
      setStatus("error");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (status === "ready") loadDetail(selected);
  }, [selected, status, loadDetail]);

  const head = (
    <PageHead
      eyebrow="ONE"
      title="Social & desarrollo"
      sub="Índice multidimensional de desarrollo por región. Se reporta la distribución, no solo el promedio. Datos ilustrativos."
    />
  );

  if (status === "loading") return <div>{head}<LoadingGrid /></div>;
  if (status === "error")
    return (
      <div>
        {head}
        <StateBlock
          kind="error"
          message="No se pudo calcular el índice de desarrollo. Reintenta."
          action={<button onClick={load} className="btn btn-ghost">Reintentar</button>}
        />
      </div>
    );

  const dist = result!.distribution;
  const cur = result!.entities.find((e) => e.entity_key === selected);
  const band = bandFor(cur?.development_score);
  const ranking = [...result!.entities].sort((a, b) => b.development_score - a.development_score);

  const rows: DimensionRow[] = detail
    ? Object.entries(detail.dimensions).map(([key, d]) => ({
        key,
        label: DIM_LABELS[key] ?? key,
        score: d.score,
        weight: d.weight,
        contribution: d.contribution,
      }))
    : [];

  // Distribution dot plot bounds
  const lo = dist.min ?? 0;
  const hi = dist.max ?? 100;
  const span = Math.max(1, hi - lo);

  return (
    <div>
      <PageHead
        eyebrow="ONE"
        title="Social & desarrollo"
        sub="Índice multidimensional de desarrollo por región. Se reporta la distribución, no solo el promedio. Datos ilustrativos."
        right={
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="field !w-auto"
            title="Región"
          >
            {result!.entities.map((e) => (
              <option key={e.entity_key} value={e.entity_key}>
                {REGION_NAMES[e.entity_key] ?? e.entity_key}
              </option>
            ))}
          </select>
        }
      />

      <div className="grid lg:grid-cols-3 gap-5">
        {/* Hero */}
        <Card className="lg:col-span-1 flex flex-col items-center text-center">
          <div className="text-xs text-muted mb-3 w-full truncate">
            {REGION_NAMES[selected] ?? selected}
          </div>
          <Gauge score={cur?.development_score} band={band} />
          <div className="mt-3">
            <BandBadge band={band} />
          </div>
          <div className="text-xs text-muted mt-3">{dist.n} regiones · IDM</div>
        </Card>

        {/* Tabs */}
        <div className="lg:col-span-2">
          <Card>
            <Tabs
              tabs={[
                { id: "distribucion", label: "Distribución" },
                { id: "desglose", label: "Desglose" },
                { id: "ranking", label: "Ranking" },
              ]}
              active={tab}
              onChange={setTab}
            />
            <div className="pt-5">
              {tab === "distribucion" && (
                <>
                  <CardHead
                    icon={BarChart3}
                    title="Distribución regional"
                    subtitle="Promedio Y dispersión (distribución > promedio)"
                  />
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
                    <StatTile label="Promedio" value={fmtNum(dist.mean, 1)} />
                    <StatTile label="Mínimo" value={fmtNum(dist.min, 1)} />
                    <StatTile label="Máximo" value={fmtNum(dist.max, 1)} />
                    <StatTile label="Amplitud" value={fmtNum(dist.spread, 1)} />
                  </div>
                  {/* dot plot */}
                  <div className="rounded-[10px] bg-surface2 p-4">
                    <div className="relative h-10">
                      {ranking.map((e) => {
                        const x = ((e.development_score - lo) / span) * 100;
                        const b = bandFor(e.development_score);
                        return (
                          <div
                            key={e.entity_key}
                            title={`${REGION_NAMES[e.entity_key] ?? e.entity_key}: ${fmtNum(e.development_score, 1)}`}
                            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3.5 h-3.5 rounded-full border-2 border-surface"
                            style={{ left: `${x}%`, background: toneVar(b.tone) }}
                          />
                        );
                      })}
                    </div>
                    <div className="flex justify-between mono text-[11px] text-muted mt-1">
                      <span>{fmtNum(dist.min, 0)}</span>
                      <span>coef. variación {dist.cv != null ? fmtNum(dist.cv * 100, 1) + "%" : "—"}</span>
                      <span>{fmtNum(dist.max, 0)}</span>
                    </div>
                  </div>
                </>
              )}

              {tab === "desglose" && (
                <>
                  <CardHead
                    icon={Users}
                    title="Dimensiones del desarrollo"
                    subtitle={`${REGION_NAMES[selected] ?? selected} · ponderadas`}
                  />
                  <DimensionBreakdown rows={rows} />
                </>
              )}

              {tab === "ranking" && (
                <>
                  <CardHead icon={ListOrdered} title="Ranking regional" subtitle="Índice de desarrollo" />
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-muted border-b border-line">
                        <th className="py-2 px-1 font-medium">#</th>
                        <th className="py-2 px-1 font-medium">Región</th>
                        <th className="py-2 px-1 font-medium text-right">IDM</th>
                        <th className="py-2 px-1 font-medium">Banda</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ranking.map((e, i) => {
                        const b = bandFor(e.development_score);
                        return (
                          <tr
                            key={e.entity_key}
                            className={`border-b border-line/60 last:border-0 ${
                              e.entity_key === selected ? "bg-accent-soft/40" : ""
                            }`}
                          >
                            <td className="py-2.5 px-1 mono text-muted">{i + 1}</td>
                            <td className="py-2.5 px-1 text-ink truncate">
                              {REGION_NAMES[e.entity_key] ?? e.entity_key}
                            </td>
                            <td className="py-2.5 px-1 text-right mono font-semibold text-ink">
                              {fmtNum(e.development_score, 1)}
                            </td>
                            <td className="py-2.5 px-1">
                              <BandBadge band={b} />
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

import { useEffect, useState, useCallback } from "react";
import { LayoutGrid, ListOrdered, Zap, Grid3x3, Activity } from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  Gauge,
  BandBadge,
  StatTile,
  Chip,
  Tabs,
  StateBlock,
  LoadingGrid,
} from "@/shared/ui/primitives";
import { DimensionBreakdown, DimensionRow } from "@/shared/ui/DimensionBreakdown";
import { Heatmap, HeatmapData } from "@/shared/charts/Heatmap";
import { bandFor } from "@/shared/lib/bands";
import { fmtNum } from "@/shared/lib/format";
import { useApp } from "@/shared/context/AppContext";
import {
  snapshot,
  getLatest,
  getMacroContext,
  SnapshotResult,
  SectorLatest,
  MacroContext,
  MacroFactor,
} from "../api";
import { Tone } from "@/shared/lib/bands";
import {
  SAMPLE_SECTORS,
  SGPS_INPUTS,
  SECTOR_NAMES,
  IAI_LABELS,
  SGPS_LABELS,
} from "../data";

type Status = "loading" | "error" | "ready";

const ACCEL_LABELS: Record<string, string> = {
  irmp: "Riesgo macro-político (IRMP)",
  trade: "Resiliencia comercial",
  macro: "Señales macro",
};

const DIRECTION_TONE: Record<string, Tone> = {
  favorable: "ok",
  adverso: "alert",
  neutral: "muted",
  "n/d": "muted",
};
const DIRECTION_LABEL: Record<string, string> = {
  favorable: "Favorable",
  adverso: "Adverso",
  neutral: "Neutral",
  "n/d": "N/D",
};
const TREND_ARROW: Record<string, string> = {
  acelerando: "↑",
  desacelerando: "↓",
  estable: "→",
};

/** One macro factor of the §2 contract: reading + direction + impacted sectors. */
function MacroFactorRow({ f, highlight }: { f: MacroFactor; highlight: string }) {
  const tone = DIRECTION_TONE[f.direction] ?? "muted";
  const hits = f.impacted_sectors.some((s) => s.slug === highlight);
  return (
    <div
      className={`rounded-[10px] border p-3 ${
        hits ? "border-accent/40 bg-accent-soft/20" : "border-line bg-surface2"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-ink truncate">{f.label}</div>
          <div className="text-xs text-muted mono mt-0.5">
            {f.reading}
            {f.trend && TREND_ARROW[f.trend] ? ` ${TREND_ARROW[f.trend]}` : ""}
          </div>
        </div>
        <div className="shrink-0 flex items-center gap-1.5">
          <Chip tone={tone}>{DIRECTION_LABEL[f.direction] ?? f.direction}</Chip>
          {f.direction !== "n/d" && f.magnitude !== "n/d" && (
            <span className="text-[11px] text-muted capitalize">{f.magnitude}</span>
          )}
        </div>
      </div>
      <p className="text-xs text-body mt-2">{f.rationale}</p>
      {(f.impacted_sectors.length > 0 || f.impacted_agents.length > 0) && (
        <div className="flex flex-wrap gap-1.5 mt-2.5">
          {f.impacted_sectors.map((s) => (
            <Chip key={s.slug} tone={s.slug === highlight ? "accent" : "muted"}>
              {s.name}
            </Chip>
          ))}
          {f.impacted_agents.map((a) => (
            <Chip key={a} tone="muted">
              {a}
            </Chip>
          ))}
        </div>
      )}
    </div>
  );
}

export function SectorIntelPage() {
  const { period } = useApp();
  const [status, setStatus] = useState<Status>("loading");
  const [snap, setSnap] = useState<SnapshotResult | null>(null);
  const [detail, setDetail] = useState<SectorLatest | null>(null);
  const [details, setDetails] = useState<Record<string, SectorLatest>>({});
  const [selected, setSelected] = useState("turismo");
  const [tab, setTab] = useState("desglose");
  const [macroCtx, setMacroCtx] = useState<MacroContext | null>(null);

  const loadDetail = useCallback(async (code: string) => {
    try {
      setDetail(await getLatest(code));
    } catch {
      setDetail(null);
    }
  }, []);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const s = await snapshot(period, SAMPLE_SECTORS, SGPS_INPUTS);
      setSnap(s);
      // Fetch every sector's breakdown to build the sector × dimension matrix.
      const all = await Promise.all(
        s.sectors.map((x) => getLatest(x.sector_code).then((d) => [x.sector_code, d] as const).catch(() => null)),
      );
      const map: Record<string, SectorLatest> = {};
      all.forEach((e) => { if (e) map[e[0]] = e[1]; });
      setDetails(map);
      setDetail(map[selected] ?? null);
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

  // §2 "Contexto macro": the macro→sectorial contract from Eje 2 (best-effort).
  useEffect(() => {
    let active = true;
    getMacroContext()
      .then((c) => { if (active) setMacroCtx(c); })
      .catch(() => { if (active) setMacroCtx(null); });
    return () => { active = false; };
  }, []);

  const head = (
    <PageHead
      eyebrow="ONE · BCRD"
      title="Sectorial"
      sub="Atractivo de inversión (IAI) y potencial de crecimiento (SGPS) por sector. La Aceleración del SGPS lee macro/IRMP/comercio. Datos ilustrativos."
    />
  );

  if (status === "loading") return <div>{head}<LoadingGrid /></div>;
  if (status === "error")
    return (
      <div>
        {head}
        <StateBlock
          kind="error"
          message="No se pudo calcular el índice sectorial. Reintenta."
          action={<button onClick={load} className="btn btn-ghost">Reintentar</button>}
        />
      </div>
    );

  const cur = snap!.sectors.find((s) => s.sector_code === selected);
  const iaiBand = bandFor(cur?.iai_score);

  const iaiRows: DimensionRow[] = detail
    ? Object.entries(detail.iai_breakdown).map(([key, d]) => ({
        key,
        label: IAI_LABELS[key] ?? key,
        score: d.score,
        weight: d.weight,
        contribution: d.contribution,
      }))
    : [];

  const sgpsRows: DimensionRow[] = detail
    ? Object.entries(detail.sgps_breakdown.factors).map(([key, f]) => ({
        key,
        label: SGPS_LABELS[key] ?? key,
        score: f.value,
        weight: f.weight,
        contribution: f.contribution,
      }))
    : [];

  const accel = snap!.acceleration;
  const ranking = [...snap!.sectors].sort((a, b) => b.iai_score - a.iai_score);

  // Sector × IAI-dimension heatmap (built from every sector's breakdown).
  const dimKeys = Object.keys(IAI_LABELS);
  const matrix: HeatmapData = {
    rows: snap!.sectors.map((s) => SECTOR_NAMES[s.sector_code] ?? s.sector_code),
    cols: dimKeys.map((k) => IAI_LABELS[k]),
    values: snap!.sectors.map((s) => {
      const d = details[s.sector_code]?.iai_breakdown;
      return dimKeys.map((k) => (d?.[k] ? d[k].score : null));
    }),
  };

  return (
    <div>
      <PageHead
        eyebrow="ONE · BCRD"
        title="Sectorial"
        sub="Atractivo de inversión (IAI) y potencial de crecimiento (SGPS) por sector. La Aceleración del SGPS lee macro/IRMP/comercio. Datos ilustrativos."
        right={
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="field !w-auto"
            title="Sector"
          >
            {snap!.sectors.map((s) => (
              <option key={s.sector_code} value={s.sector_code}>
                {SECTOR_NAMES[s.sector_code] ?? s.sector_code}
              </option>
            ))}
          </select>
        }
      />

      <div className="grid lg:grid-cols-3 gap-5">
        {/* Hero */}
        <Card className="lg:col-span-1 flex flex-col items-center text-center">
          <div className="text-xs text-muted mb-1 w-full truncate">
            {SECTOR_NAMES[selected] ?? selected}
          </div>
          <div className="mono text-[10px] uppercase tracking-[0.16em] text-accent mb-2">IAI</div>
          <Gauge score={cur?.iai_score} band={iaiBand} />
          <div className="mt-3">
            <BandBadge band={iaiBand} />
          </div>
          <div className="grid grid-cols-2 gap-3 w-full mt-5">
            <div className="rounded-[10px] bg-surface2 p-3">
              <div className="text-[11px] text-muted">SGPS</div>
              <div className="font-display text-xl font-extrabold text-ink mono mt-0.5">
                {fmtNum(cur?.sgps_score, 1)}
              </div>
            </div>
            <div className="rounded-[10px] bg-surface2 p-3">
              <div className="text-[11px] text-muted">Aceleración</div>
              <div className="font-display text-xl font-extrabold text-ink mono mt-0.5">
                {fmtNum(accel.acceleration, 1)}
              </div>
            </div>
          </div>
        </Card>

        {/* Tabs */}
        <div className="lg:col-span-2">
          <Card>
            <Tabs
              tabs={[
                { id: "desglose", label: "Desglose" },
                { id: "contexto", label: "Contexto macro" },
                { id: "matriz", label: "Matriz" },
                { id: "ranking", label: "Ranking" },
                { id: "aceleracion", label: "Aceleración" },
              ]}
              active={tab}
              onChange={setTab}
            />
            <div className="pt-5">
              {tab === "desglose" && (
                <div className="space-y-6">
                  <div>
                    <CardHead
                      icon={LayoutGrid}
                      title="IAI — dimensiones"
                      subtitle={`${SECTOR_NAMES[selected] ?? selected} · ponderadas`}
                    />
                    <DimensionBreakdown rows={iaiRows} />
                  </div>
                  <div>
                    <CardHead
                      title="SGPS — factores"
                      subtitle="Histórico 40 · Estructural 35 · Aceleración 25"
                    />
                    <DimensionBreakdown rows={sgpsRows} />
                  </div>
                </div>
              )}

              {tab === "contexto" && (
                <>
                  <CardHead
                    icon={Activity}
                    title="Contexto macro"
                    subtitle={
                      macroCtx
                        ? `${macroCtx.available_count}/${macroCtx.factor_count} factores en vivo${
                            macroCtx.period ? ` · ${macroCtx.period}` : ""
                          } · resaltado: ${SECTOR_NAMES[selected] ?? selected}`
                        : "Entorno macro del BCRD (Eje 2)"
                    }
                  />
                  {!macroCtx ? (
                    <p className="text-sm text-muted">Cargando el contexto macro…</p>
                  ) : macroCtx.factors.length === 0 ? (
                    <p className="text-sm text-muted">Sin factores macro disponibles.</p>
                  ) : (
                    <div className="space-y-3">
                      {macroCtx.factors.map((f) => (
                        <MacroFactorRow key={f.key} f={f} highlight={selected} />
                      ))}
                    </div>
                  )}
                </>
              )}

              {tab === "matriz" && (
                <>
                  <CardHead
                    icon={Grid3x3}
                    title="Matriz IAI"
                    subtitle="Sector × dimensión · intensidad por score"
                  />
                  <Heatmap data={matrix} />
                </>
              )}

              {tab === "ranking" && (
                <>
                  <CardHead icon={ListOrdered} title="Ranking por IAI" subtitle="Atractivo de inversión" />
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-muted border-b border-line">
                        <th className="py-2 px-1 font-medium">#</th>
                        <th className="py-2 px-1 font-medium">Sector</th>
                        <th className="py-2 px-1 font-medium text-right">IAI</th>
                        <th className="py-2 px-1 font-medium text-right">SGPS</th>
                        <th className="py-2 px-1 font-medium">Banda</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ranking.map((r, i) => {
                        const b = bandFor(r.iai_score);
                        return (
                          <tr
                            key={r.sector_code}
                            className={`border-b border-line/60 last:border-0 ${
                              r.sector_code === selected ? "bg-accent-soft/40" : ""
                            }`}
                          >
                            <td className="py-2.5 px-1 mono text-muted">{i + 1}</td>
                            <td className="py-2.5 px-1 text-ink truncate">
                              {SECTOR_NAMES[r.sector_code] ?? r.sector_code}
                            </td>
                            <td className="py-2.5 px-1 text-right mono font-semibold text-ink">
                              {fmtNum(r.iai_score, 1)}
                            </td>
                            <td className="py-2.5 px-1 text-right mono text-body">
                              {fmtNum(r.sgps_score, 1)}
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

              {tab === "aceleracion" && (
                <>
                  <CardHead
                    icon={Zap}
                    title="Factor de aceleración"
                    subtitle="Entorno upstream (macro · IRMP · comercio) vía event_bus"
                  />
                  <div className="flex items-baseline gap-2 mb-4">
                    <span className="font-display text-3xl font-extrabold text-ink mono">
                      {fmtNum(accel.acceleration, 1)}
                    </span>
                    <span className="text-xs text-muted">base {fmtNum(accel.base, 0)}</span>
                  </div>
                  {Object.keys(accel.components).length === 0 ? (
                    <p className="text-sm text-muted">
                      Sin señales upstream aún. Genera snapshots de IRMP/comercio/macro para
                      alimentar la aceleración.
                    </p>
                  ) : (
                    <div className="space-y-2">
                      {Object.entries(accel.components).map(([k, v]) => (
                        <div
                          key={k}
                          className="flex items-center justify-between gap-3 py-1.5 border-b border-line/60 last:border-0"
                        >
                          <span className="text-sm text-ink">{ACCEL_LABELS[k] ?? k}</span>
                          <Chip tone={v >= 0 ? "ok" : "alert"}>
                            {v >= 0 ? "+" : ""}
                            {fmtNum(v, 1)}
                          </Chip>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

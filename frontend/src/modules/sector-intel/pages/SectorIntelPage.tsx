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
import { ValidationTab } from "../components/ValidationTab";
import { DimensionBreakdown, DimensionRow } from "@/shared/ui/DimensionBreakdown";
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import { Heatmap, HeatmapData } from "@/shared/charts/Heatmap";
import { bandFor } from "@/shared/lib/bands";
import { fmtNum } from "@/shared/lib/format";
import {
  getSectors,
  getDataset,
  getLatest,
  getMacroContext,
  getSectorInsight,
  SectorInfo,
  SectorLatest,
  IaiDataset,
  MacroContext,
  MacroFactor,
} from "../api";
import { IAI_LABELS, SGPS_LABELS, IAI_DIM_VARS } from "../data";
import { Tone } from "@/shared/lib/bands";

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

/** Real-vs-rubric tag for one IAI dimension, from the dataset's sources map. */
function dimTag(
  sources: Record<string, string> | undefined,
  dimKey: string,
): DimensionRow["tag"] {
  const vars = IAI_DIM_VARS[dimKey] ?? [];
  if (!sources || vars.length === 0) return undefined;
  const live = vars.filter((v) => sources[v] === "live").length;
  if (live === 0) return { text: "rúbrica", ok: false };
  if (live === vars.length) return { text: "en vivo", ok: true };
  return { text: `${live}/${vars.length} en vivo`, ok: true };
}

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
  const [status, setStatus] = useState<Status>("loading");
  const [sectors, setSectors] = useState<SectorInfo[]>([]);
  const [ds, setDs] = useState<IaiDataset | null>(null);
  const [details, setDetails] = useState<Record<string, SectorLatest>>({});
  const [selected, setSelected] = useState("turismo");
  const [tab, setTab] = useState("desglose");
  const [macroCtx, setMacroCtx] = useState<MacroContext | null>(null);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const [secs, dataset] = await Promise.all([getSectors(), getDataset()]);
      setSectors(secs);
      setDs(dataset);
      const all = await Promise.all(
        secs.map((s) =>
          getLatest(s.code).then((d) => [s.code, d] as const).catch(() => null),
        ),
      );
      const map: Record<string, SectorLatest> = {};
      all.forEach((e) => { if (e && e[1].has_score) map[e[0]] = e[1]; });
      setDetails(map);
      setSelected((prev) => (map[prev] ? prev : secs.find((s) => map[s.code])?.code ?? prev));
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // §2 "Contexto macro": the macro→sectorial contract from Eje 2 (best-effort).
  useEffect(() => {
    let active = true;
    getMacroContext()
      .then((c) => { if (active) setMacroCtx(c); })
      .catch(() => { if (active) setMacroCtx(null); });
    return () => { active = false; };
  }, []);

  const names: Record<string, string> = Object.fromEntries(
    sectors.map((s) => [s.code, s.name]),
  );
  const nameOf = (code: string) => names[code] ?? code;

  const head = (
    <PageHead
      eyebrow="BCRD · macro · WGI · rúbrica"
      title="Sectorial"
      sub="Atractivo de inversión (IAI) y potencial de crecimiento (SGPS) por sector. Tamaño y crecimiento del BCRD; exposición macro del contrato del Eje 2; calidad regulatoria del WGI (nacional); negocios y talento, rúbrica declarada."
    />
  );

  if (status === "loading") return <div>{head}<LoadingGrid /></div>;
  if (status === "error")
    return (
      <div>
        {head}
        <StateBlock
          kind="error"
          message="No se pudo cargar el índice sectorial. Reintenta."
          action={<button onClick={load} className="btn btn-ghost">Reintentar</button>}
        />
      </div>
    );

  const scored = sectors.filter((s) => details[s.code]);
  if (scored.length === 0)
    return (
      <div>
        {head}
        <StateBlock
          kind="empty"
          message="Aún no hay snapshot sectorial. Corre la operación «Calcular snapshot sectorial (IAI/SGPS)» en la Consola de Operación."
        />
      </div>
    );

  const detail = details[selected] ?? null;
  const sources = ds?.sources[selected];
  const iaiBand = bandFor(detail?.iai_score);

  const iaiRows: DimensionRow[] = detail
    ? Object.entries(detail.iai_breakdown).map(([key, d]) => ({
        key,
        label: IAI_LABELS[key] ?? key,
        score: d.score,
        weight: d.weight,
        contribution: d.contribution,
        tag: dimTag(sources, key),
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

  const accel = detail?.sgps_breakdown.acceleration_detail;
  const ranking = [...scored]
    .map((s) => ({ code: s.code, ...details[s.code] }))
    .sort((a, b) => b.iai_score - a.iai_score);

  const dimKeys = Object.keys(IAI_LABELS);
  const matrix: HeatmapData = {
    rows: scored.map((s) => nameOf(s.code)),
    cols: dimKeys.map((k) => IAI_LABELS[k]),
    values: scored.map((s) => {
      const d = details[s.code]?.iai_breakdown;
      return dimKeys.map((k) => (d?.[k] ? d[k].score : null));
    }),
  };

  const liveDims = sources
    ? dimKeys.filter((k) => dimTag(sources, k)?.ok).length
    : 0;

  return (
    <div>
      <PageHead
        eyebrow="BCRD · macro · WGI · rúbrica"
        title="Sectorial"
        sub="Atractivo de inversión (IAI) y potencial de crecimiento (SGPS) por sector. Tamaño y crecimiento del BCRD; exposición macro del contrato del Eje 2; calidad regulatoria del WGI (nacional); negocios y talento, rúbrica declarada."
        right={
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="field !w-auto"
            title="Sector"
          >
            {scored.map((s) => (
              <option key={s.code} value={s.code}>{nameOf(s.code)}</option>
            ))}
          </select>
        }
      />

      <div className="flex flex-wrap items-center gap-2 mb-4 -mt-2">
        <Chip tone={ds?.has_live ? "ok" : "muted"}>
          {liveDims}/{dimKeys.length} dimensiones en vivo
        </Chip>
        {ds?.period && <Chip tone="muted">{ds.period}</Chip>}
        <Chip tone="muted">{scored.length} sectores</Chip>
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        {/* Hero */}
        <Card className="lg:col-span-1 flex flex-col items-center text-center">
          <div className="text-xs text-muted mb-1 w-full truncate">{nameOf(selected)}</div>
          <div className="mono text-[10px] uppercase tracking-[0.16em] text-accent mb-2">IAI</div>
          <Gauge score={detail?.iai_score} band={iaiBand} />
          <div className="mt-3"><BandBadge band={iaiBand} /></div>
          <div className="grid grid-cols-2 gap-3 w-full mt-5">
            <StatTile label="SGPS" value={fmtNum(detail?.sgps_score, 1)} />
            <StatTile label="Aceleración" value={fmtNum(accel?.acceleration, 1)} />
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
                { id: "validacion", label: "Validación" },
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
                      subtitle={`${nameOf(selected)} · ponderadas · badge real-vs-rúbrica`}
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
                          } · resaltado: ${nameOf(selected)}`
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
                            key={r.code}
                            className={`border-b border-line/60 last:border-0 ${
                              r.code === selected ? "bg-accent-soft/40" : ""
                            }`}
                          >
                            <td className="py-2.5 px-1 mono text-muted">{i + 1}</td>
                            <td className="py-2.5 px-1 text-ink truncate">{nameOf(r.code)}</td>
                            <td className="py-2.5 px-1 text-right mono font-semibold text-ink">
                              {fmtNum(r.iai_score, 1)}
                            </td>
                            <td className="py-2.5 px-1 text-right mono text-body">
                              {fmtNum(r.sgps_score, 1)}
                            </td>
                            <td className="py-2.5 px-1"><BandBadge band={b} /></td>
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
                      {fmtNum(accel?.acceleration, 1)}
                    </span>
                    <span className="text-xs text-muted">base {fmtNum(accel?.base, 0)}</span>
                  </div>
                  {!accel || Object.keys(accel.components).length === 0 ? (
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
                            {v >= 0 ? "+" : ""}{fmtNum(v, 1)}
                          </Chip>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
              {tab === "validacion" && <ValidationTab />}
            </div>
          </Card>
        </div>
      </div>

      <div className="mt-5">
        <AiInsightCard
          title="Perspectiva del sector (IA)"
          subtitle={`${nameOf(selected)} · IAI + aceleración, marco SCQA`}
          depsKey={selected}
          fetcher={() => getSectorInsight(selected)}
        />
      </div>
    </div>
  );
}

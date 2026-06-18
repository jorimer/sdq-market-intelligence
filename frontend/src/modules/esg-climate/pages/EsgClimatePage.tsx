import { useEffect, useState, useCallback } from "react";
import { Leaf, ListOrdered, ShieldCheck } from "lucide-react";
import {
  PageHead,
  Card,
  CardHead,
  Gauge,
  Chip,
  Tabs,
  StatTile,
  StateBlock,
  LoadingGrid,
} from "@/shared/ui/primitives";
import { DimensionBreakdown, DimensionRow } from "@/shared/ui/DimensionBreakdown";
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import { Band } from "@/shared/lib/bands";
import { fmtNum } from "@/shared/lib/format";
import { getIndicators, getCountryScore, getCountryInsight, getBacktest, IRCIndicator, IRCCountryDetail, IRCBacktest } from "../api";
import { DIM_LABELS, IRC_DIM_VARS } from "../data";

type Status = "loading" | "error" | "ready";

// Higher IRC = more resilient / lower climate risk.
function ircBand(score: number | null | undefined): Band {
  if (score == null) return { label: "Sin dato", tone: "muted" };
  if (score >= 60) return { label: "Resiliencia alta", tone: "ok" };
  if (score >= 40) return { label: "Resiliencia moderada", tone: "warn" };
  return { label: "Resiliencia baja", tone: "alert" };
}

/** Real-vs-rubric tag for one IRC dimension, from the source map. */
function dimTag(
  sources: Record<string, string> | undefined,
  dimKey: string,
): DimensionRow["tag"] {
  const vars = IRC_DIM_VARS[dimKey] ?? [];
  if (!sources || vars.length === 0) return undefined;
  const live = vars.filter((v) => sources[v] === "live").length;
  if (live === 0) return { text: "rúbrica", ok: false };
  if (live === vars.length) return { text: "en vivo", ok: true };
  return { text: `${live}/${vars.length} en vivo`, ok: true };
}

export function EsgClimatePage() {
  const [status, setStatus] = useState<Status>("loading");
  const [countries, setCountries] = useState<IRCIndicator[]>([]);
  const [detail, setDetail] = useState<IRCCountryDetail | null>(null);
  const [selected, setSelected] = useState("DOM");
  const [tab, setTab] = useState("desglose");
  const [backtest, setBacktest] = useState<IRCBacktest | null>(null);

  useEffect(() => {
    getBacktest().then(setBacktest).catch(() => setBacktest(null));
  }, []);

  const loadDetail = useCallback(async (key: string) => {
    try {
      setDetail(await getCountryScore(key));
    } catch {
      setDetail(null);
    }
  }, []);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const r = await getIndicators();
      setCountries(r.indicators);
      setSelected((prev) =>
        r.indicators.some((c) => c.entity_key === prev)
          ? prev
          : r.indicators.find((c) => c.entity_key === "DOM")?.entity_key
            ?? r.indicators[0]?.entity_key ?? prev,
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

  const nameOf = (key: string) =>
    countries.find((c) => c.entity_key === key)?.country_name ?? key;

  const head = (
    <PageHead
      eyebrow="ND-GAIN · panel Caribe/LatAm"
      title="ESG & clima"
      sub="Índice de Resiliencia Climática (IRC) nacional sobre el panel regional. Mayor score = mayor resiliencia. Físico/adaptativa/gobernanza con dato real (ND-GAIN); transición, rúbrica hasta cablear energía."
    />
  );

  if (status === "loading") return <div>{head}<LoadingGrid /></div>;
  if (status === "error")
    return (
      <div>
        {head}
        <StateBlock kind="error" message="No se pudo cargar el IRC. Reintenta."
          action={<button onClick={load} className="btn btn-ghost">Reintentar</button>} />
      </div>
    );

  if (countries.length === 0)
    return (
      <div>
        {head}
        <StateBlock kind="empty"
          message="Aún no hay IRC. Corre la operación «Sincronizar IRC climático (ND-GAIN)» en la Consola de Operación." />
      </div>
    );

  const cur = countries.find((c) => c.entity_key === selected);
  const band = ircBand(cur?.esg_score);
  const ranking = [...countries].sort((a, b) => b.esg_score - a.esg_score); // most resilient first
  const sources = detail?.breakdown?.sources;
  const dims = detail?.breakdown?.dimensions ?? {};
  const rows: DimensionRow[] = Object.entries(dims).map(([key, d]) => ({
    key,
    label: DIM_LABELS[key] ?? key,
    score: d.score,
    weight: d.weight,
    contribution: d.contribution,
    tag: dimTag(sources, key),
  }));

  return (
    <div>
      <PageHead
        eyebrow="ND-GAIN · panel Caribe/LatAm"
        title="ESG & clima"
        sub={`Índice de Resiliencia Climática (IRC) · ${cur?.period ?? ""}. Mayor = mayor resiliencia.`}
        right={
          <select value={selected} onChange={(e) => setSelected(e.target.value)}
            className="field !w-auto" title="País">
            {countries.map((c) => (
              <option key={c.entity_key} value={c.entity_key}>{c.country_name}</option>
            ))}
          </select>
        }
      />

      <div className="grid lg:grid-cols-3 gap-5">
        {/* Hero */}
        <Card className="lg:col-span-1 flex flex-col items-center text-center">
          <div className="text-xs text-muted mb-1 w-full truncate">{nameOf(selected)}</div>
          <div className="mono text-[10px] uppercase tracking-[0.16em] text-accent mb-2">IRC</div>
          <Gauge score={cur?.esg_score} band={band} />
          <div className="mt-3"><Chip tone={band.tone}>{band.label}</Chip></div>
          <div className="text-xs text-muted mt-3">{countries.length} países · panel regional</div>
        </Card>

        {/* Tabs */}
        <div className="lg:col-span-2">
          <Card>
            <Tabs
              tabs={[
                { id: "desglose", label: "Desglose" },
                { id: "ranking", label: "Ranking del panel" },
                { id: "validacion", label: "Validación" },
              ]}
              active={tab}
              onChange={setTab}
            />
            <div className="pt-5">
              {tab === "desglose" && (
                <>
                  <CardHead icon={Leaf} title="Dimensiones del IRC"
                    subtitle={`${nameOf(selected)} · ponderadas · badge real-vs-rúbrica`} />
                  <DimensionBreakdown rows={rows} />
                </>
              )}

              {tab === "ranking" && (
                <>
                  <CardHead icon={ListOrdered} title="Ranking de resiliencia climática"
                    subtitle="Más resiliente primero" />
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-muted border-b border-line">
                        <th className="py-2 px-1 font-medium">#</th>
                        <th className="py-2 px-1 font-medium">País</th>
                        <th className="py-2 px-1 font-medium text-right">IRC</th>
                        <th className="py-2 px-1 font-medium">Resiliencia</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ranking.map((c, i) => {
                        const b = ircBand(c.esg_score);
                        return (
                          <tr key={c.entity_key}
                            className={`border-b border-line/60 last:border-0 ${
                              c.entity_key === selected ? "bg-accent-soft/40" : ""}`}>
                            <td className="py-2.5 px-1 mono text-muted">{i + 1}</td>
                            <td className="py-2.5 px-1 text-ink truncate">{c.country_name}</td>
                            <td className="py-2.5 px-1 text-right mono font-semibold text-ink">
                              {fmtNum(c.esg_score, 1)}
                            </td>
                            <td className="py-2.5 px-1"><Chip tone={b.tone}>{b.label}</Chip></td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </>
              )}

              {tab === "validacion" && (
                <>
                  <CardHead icon={ShieldCheck} title="Backtest del IRC"
                    subtitle="¿La resiliencia predice menos daño climático real? (OWID/EM-DAT)" />
                  {!backtest?.computed ? (
                    <StateBlock kind="empty"
                      message={backtest?.message ?? "Aún no hay backtest. Corre «Backtest del IRC climático» en la Consola de Operación."} />
                  ) : (
                    <div className="space-y-4">
                      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                        <StatTile label="Correlación (Spearman)" value={fmtNum(backtest.spearman ?? null, 3)} />
                        <StatTile label="IC 95%"
                          value={backtest.spearman_ci
                            ? `${fmtNum(backtest.spearman_ci[0] ?? null, 2)} … ${fmtNum(backtest.spearman_ci[1] ?? null, 2)}`
                            : "—"} />
                        <StatTile label="Países" value={backtest.n_countries ?? "—"} />
                      </div>
                      <div className="flex items-center gap-2">
                        <Chip tone={backtest.monotonic ? "ok" : "warn"}>
                          {backtest.monotonic ? "Monótona ✓" : "No monótona"}
                        </Chip>
                        <span className="text-xs text-muted">
                          mayor resiliencia → menos muertes por desastre climático
                        </span>
                      </div>
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-left text-xs text-muted border-b border-line">
                            <th className="py-2 px-1 font-medium">Banda IRC</th>
                            <th className="py-2 px-1 font-medium text-right">Países</th>
                            <th className="py-2 px-1 font-medium text-right">Muertes/100k/año</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(backtest.by_band ?? []).map((b) => (
                            <tr key={b.band} className="border-b border-line/60 last:border-0">
                              <td className="py-2.5 px-1 text-ink">{b.band}</td>
                              <td className="py-2.5 px-1 text-right mono text-body">{b.n}</td>
                              <td className="py-2.5 px-1 text-right mono text-ink">
                                {fmtNum(b.mean_climate_deaths_per_100k ?? null, 3)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {backtest.note && <p className="text-xs text-muted">{backtest.note}</p>}
                    </div>
                  )}
                </>
              )}
            </div>
          </Card>
        </div>
      </div>

      <div className="mt-5">
        <AiInsightCard
          title="Perspectiva climática (IA)"
          subtitle={`${nameOf(selected)} · IRC + posición en el panel · SCQA`}
          depsKey={selected}
          fetcher={() => getCountryInsight(selected)}
        />
      </div>
    </div>
  );
}

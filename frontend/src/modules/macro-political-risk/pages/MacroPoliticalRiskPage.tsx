import { useEffect, useState, useCallback } from "react";
import { Scale, ListOrdered, SlidersHorizontal, ShieldAlert } from "lucide-react";
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import {
  PageHead,
  Card,
  CardHead,
  Gauge,
  BandBadge,
  Chip,
  Tabs,
  StateBlock,
  LoadingGrid,
} from "@/shared/ui/primitives";
import { DimensionBreakdown, DimensionRow } from "@/shared/ui/DimensionBreakdown";
import { ValidationTab } from "../components/ValidationTab";
import { riskBandFor } from "@/shared/lib/bands";
import { fmtNum } from "@/shared/lib/format";
import { useApp } from "@/shared/context/AppContext";
import {
  getWeights,
  getDataset,
  scoreCountry,
  saveSnapshot,
  IRMPResult,
  IRMPWeights,
} from "../api";
import {
  SAMPLE_REGIONAL,
  COUNTRY_NAMES,
  DIMENSION_LABELS,
} from "../data";

type Status = "loading" | "error" | "ready";
type Dataset = Record<string, Record<string, number>>;
type SourceMap = Record<string, Record<string, "live" | "rubric">>;

interface LiveInfo {
  period: string | null;
  covered: number;        // countries with ≥1 live variable
  total: number;
  variables: number;      // distinct live/declared variables
  live: boolean;
}

function periodEndFor(period: string): string {
  const q: Record<string, string> = { Q1: "03-31", Q2: "06-30", Q3: "09-30", Q4: "12-31" };
  const m = period.match(/^(\d{4})-(Q[1-4])$/);
  if (m) return `${m[1]}-${q[m[2]]}`;
  if (/^\d{4}$/.test(period)) return `${period}-12-31`;
  return "2025-12-31";
}

export function MacroPoliticalRiskPage() {
  const { period } = useApp();
  const [status, setStatus] = useState<Status>("loading");
  const [results, setResults] = useState<Record<string, IRMPResult>>({});
  const [weights, setWeights] = useState<IRMPWeights | null>(null);
  const [selected, setSelected] = useState("DO");
  const [tab, setTab] = useState("desglose");
  const [saved, setSaved] = useState<string | null>(null);
  const [dataset, setDataset] = useState<Dataset>(SAMPLE_REGIONAL);
  const [sources, setSources] = useState<SourceMap>({});
  const [dataPeriod, setDataPeriod] = useState<string | null>(null);
  const [liveInfo, setLiveInfo] = useState<LiveInfo>({
    period: null, covered: 0, total: Object.keys(SAMPLE_REGIONAL).length, variables: 0, live: false,
  });

  // Presentation country list: fixture order first, plus any extra country the
  // backend actually scored (so a doctrine/live addition isn't silently hidden
  // from the ranking and selector).
  const codes = [...new Set([...Object.keys(SAMPLE_REGIONAL), ...Object.keys(results)])];

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      // Single source of truth: the backend assembles declared rubric + live data
      // (real wins). Best-effort: if it fails or has no live data, fall back to the
      // illustrative fixture so the page never breaks.
      let data: Dataset = SAMPLE_REGIONAL;
      let smap: SourceMap = {};
      let dperiod: string | null = null;
      let info: LiveInfo = { period: null, covered: 0, total: codes.length, variables: 0, live: false };
      try {
        const asm = await getDataset();
        if (asm.has_live && Object.keys(asm.dataset).length) {
          data = asm.dataset;
          smap = asm.sources;
          dperiod = asm.period;
          const liveVars = new Set<string>();
          let covered = 0;
          for (const iso of Object.keys(asm.sources)) {
            const live = Object.entries(asm.sources[iso]).filter(([, s]) => s === "live");
            if (live.length) covered += 1;
            live.forEach(([v]) => liveVars.add(v));
          }
          info = { period: asm.period, covered, total: Object.keys(asm.dataset).length,
                   variables: liveVars.size, live: covered > 0 };
        }
      } catch {
        /* keep fixture — degradación elegante */
      }

      const dataCodes = Object.keys(data);
      const [w, ...scores] = await Promise.all([
        getWeights(),
        ...dataCodes.map((c) => scoreCountry(c, data)),
      ]);
      const map: Record<string, IRMPResult> = {};
      scores.forEach((s) => (map[s.country_code] = s));
      setWeights(w);
      setResults(map);
      setDataset(data);
      setSources(smap);
      setDataPeriod(dperiod);
      setLiveInfo(info);
      setStatus("ready");
    } catch {
      setStatus("error");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const head = (
    <PageHead
      eyebrow="WGI · BCRD · SIB"
      title="Regulatorio & político"
      sub="Índice de Riesgo Macro-Político (IRMP): mayor score = menor riesgo. Determinista y auditable. Macro/externa/gobernanza en vivo (WGI · WDI · IMF) + rating declarado; variables de juicio aún ilustrativas."
    />
  );

  if (status === "loading") return <div>{head}<LoadingGrid /></div>;
  if (status === "error")
    return (
      <div>
        {head}
        <StateBlock
          kind="error"
          message="No se pudo calcular el IRMP. Verifica el backend y reintenta."
          action={<button onClick={load} className="btn btn-ghost">Reintentar</button>}
        />
      </div>
    );

  const cur = results[selected];
  const band = riskBandFor(cur?.irmp_score);
  const sel = sources[selected] ?? {};
  const rows: DimensionRow[] = cur
    ? Object.entries(cur.dimensions).map(([key, d]) => {
        const vars = weights?.dimension_variables[key] ?? [];
        const live = vars.filter((v) => sel[v] === "live").length;
        const tag: DimensionRow["tag"] =
          vars.length === 0 || Object.keys(sel).length === 0
            ? undefined
            : live === vars.length
            ? { text: "en vivo", ok: true }
            : live === 0
            ? { text: "rúbrica" }
            : { text: `${live}/${vars.length} en vivo`, ok: live >= vars.length / 2 };
        return {
          key,
          label: DIMENSION_LABELS[key] ?? key,
          score: d.score,
          weight: d.weight,
          contribution: d.contribution,
          tag,
        };
      })
    : [];

  const ranking = [...codes]
    .map((c) => results[c])
    .filter(Boolean)
    .sort((a, b) => b.irmp_score - a.irmp_score);

  // Persist at the data vintage (e.g. 2024) so the manual save and the scheduled
  // irmp-snapshot operation key snapshots the same way.
  const snapPeriod = periodEndFor(dataPeriod ?? period);
  const doSave = async () => {
    setSaved(null);
    try {
      await saveSnapshot(selected, dataset, snapPeriod, COUNTRY_NAMES[selected]);
      setSaved(`Snapshot guardado (${snapPeriod}) · evento irmp.updated publicado`);
    } catch {
      setSaved("No se pudo guardar el snapshot.");
    }
  };

  return (
    <div>
      <PageHead
        eyebrow="WGI · BCRD · SIB"
        title="Regulatorio & político"
        sub="Índice de Riesgo Macro-Político (IRMP): mayor score = menor riesgo. Determinista y auditable. Macro/externa/gobernanza en vivo (WGI · WDI · IMF) + rating declarado; variables de juicio aún ilustrativas."
        right={
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="field !w-auto"
            title="País"
          >
            {codes.map((c) => (
              <option key={c} value={c}>
                {COUNTRY_NAMES[c] ?? c}
              </option>
            ))}
          </select>
        }
      />

      <div className="grid lg:grid-cols-3 gap-5">
        {/* Hero */}
        <Card className="lg:col-span-1 flex flex-col items-center text-center">
          <div className="text-xs text-muted mb-3 truncate w-full">
            {COUNTRY_NAMES[selected] ?? selected}
          </div>
          <Gauge score={cur?.irmp_score} band={band} />
          <div className="mt-3">
            <BandBadge band={band} />
          </div>
          <div className="mt-3 text-xs text-muted">
            Conjunto regional: {cur?.peer_set_size ?? codes.length} países
          </div>
          <div className="mt-2">
            {liveInfo.live ? (
              <Chip tone="ok">
                {liveInfo.variables} variables en vivo · {liveInfo.period} · {liveInfo.covered}/{liveInfo.total} países
              </Chip>
            ) : (
              <Chip tone="muted">Datos ilustrativos · sync pendiente</Chip>
            )}
          </div>
          <button onClick={doSave} className="btn btn-soft mt-4 w-full">
            Guardar snapshot
          </button>
          {saved && <div className="text-xs text-muted mt-2">{saved}</div>}
        </Card>

        {/* Tabs: desglose / ranking */}
        <div className="lg:col-span-2">
          <Card>
            <Tabs
              tabs={[
                { id: "desglose", label: "Desglose explicable" },
                { id: "ranking", label: "Ranking regional" },
                { id: "pesos", label: "Pesos" },
                { id: "validacion", label: "Validación" },
              ]}
              active={tab}
              onChange={setTab}
            />

            <div className="pt-5">
              {tab === "desglose" && (
                <>
                  <CardHead
                    icon={Scale}
                    title="Dimensiones ponderadas"
                    subtitle={`${COUNTRY_NAMES[selected] ?? selected} · contribución al IRMP`}
                  />
                  <DimensionBreakdown rows={rows} />
                </>
              )}

              {tab === "ranking" && (
                <>
                  <CardHead
                    icon={ListOrdered}
                    title="Ranking regional"
                    subtitle="Mayor score = menor riesgo"
                  />
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-muted border-b border-line">
                        <th className="py-2 px-1 font-medium">#</th>
                        <th className="py-2 px-1 font-medium">País</th>
                        <th className="py-2 px-1 font-medium text-right">IRMP</th>
                        <th className="py-2 px-1 font-medium">Banda</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ranking.map((r, i) => {
                        const b = riskBandFor(r.irmp_score);
                        return (
                          <tr
                            key={r.country_code}
                            className={`border-b border-line/60 last:border-0 ${
                              r.country_code === selected ? "bg-accent-soft/40" : ""
                            }`}
                          >
                            <td className="py-2.5 px-1 mono text-muted">{i + 1}</td>
                            <td className="py-2.5 px-1 text-ink truncate">
                              {COUNTRY_NAMES[r.country_code] ?? r.country_code}
                            </td>
                            <td className="py-2.5 px-1 text-right mono font-semibold text-ink">
                              {fmtNum(r.irmp_score, 1)}
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

              {tab === "pesos" && weights && (
                <>
                  <CardHead
                    icon={SlidersHorizontal}
                    title="Ponderaciones del índice"
                    subtitle={weights.direction}
                  />
                  <div className="space-y-2">
                    {Object.entries(weights.dimension_weights).map(([k, w]) => (
                      <div
                        key={k}
                        className="flex items-center justify-between gap-3 py-1.5 border-b border-line/60 last:border-0"
                      >
                        <span className="text-sm text-ink">{DIMENSION_LABELS[k] ?? k}</span>
                        <Chip tone="accent">{Math.round(w * 100)}%</Chip>
                      </div>
                    ))}
                  </div>
                </>
              )}

              {tab === "validacion" && <ValidationTab />}
            </div>
          </Card>
        </div>
      </div>

      {cur && (
        <div className="mt-5">
          <AiInsightCard
            title="Evaluación de riesgo (IA)"
            subtitle={`${COUNTRY_NAMES[selected] ?? selected} · IRMP ${fmtNum(cur.irmp_score, 1)} · ${band.label}`}
            icon={ShieldAlert}
            depsKey={`${selected}:${liveInfo.period ?? "fix"}`}
            fetcher={() =>
              scoreCountry(selected, dataset, {
                withAi: true,
                countryName: COUNTRY_NAMES[selected],
              }).then((r) => r.ai_insight ?? null)
            }
          />
        </div>
      )}
    </div>
  );
}

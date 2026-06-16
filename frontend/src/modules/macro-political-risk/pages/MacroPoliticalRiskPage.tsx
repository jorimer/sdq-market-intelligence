import { useEffect, useState, useCallback } from "react";
import { Scale, ListOrdered, SlidersHorizontal } from "lucide-react";
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
import { riskBandFor } from "@/shared/lib/bands";
import { fmtNum } from "@/shared/lib/format";
import { useApp } from "@/shared/context/AppContext";
import {
  getWeights,
  getWgiLive,
  scoreCountry,
  saveSnapshot,
  IRMPResult,
  IRMPWeights,
  WgiLive,
} from "../api";
import {
  SAMPLE_REGIONAL,
  COUNTRY_NAMES,
  DIMENSION_LABELS,
} from "../data";

type Status = "loading" | "error" | "ready";
type Dataset = Record<string, Record<string, number>>;

// The three governance inputs sourced live from World Bank WGI; the rest of the
// regional dataset stays illustrative until its own source is wired.
const WGI_KEYS = ["wgi_rule_of_law", "wgi_gov_effectiveness", "wgi_control_corruption"];

interface WgiInfo {
  period: string | null;
  covered: number;
  total: number;
  live: boolean;
}

// Overlay live WGI values onto the fixture dataset, only where a real number
// exists. Missing live values keep the declared fixture — never fabricated.
function mergeWgi(base: Dataset, live: WgiLive): Dataset {
  const merged: Dataset = {};
  for (const [iso, vars] of Object.entries(base)) {
    const liveVars = live.countries[iso] ?? {};
    const next = { ...vars };
    for (const k of WGI_KEYS) {
      if (typeof liveVars[k] === "number") next[k] = liveVars[k];
    }
    merged[iso] = next;
  }
  return merged;
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
  const [wgiInfo, setWgiInfo] = useState<WgiInfo>({
    period: null, covered: 0, total: Object.keys(SAMPLE_REGIONAL).length, live: false,
  });

  const codes = Object.keys(SAMPLE_REGIONAL);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      // Live WGI overlay is best-effort: if the sync hasn't run or the call
      // fails, fall back to the fixture so the page never breaks.
      let merged: Dataset = SAMPLE_REGIONAL;
      let info: WgiInfo = { period: null, covered: 0, total: codes.length, live: false };
      try {
        const live = await getWgiLive();
        if (live.has_data) {
          merged = mergeWgi(SAMPLE_REGIONAL, live);
          const covered = codes.filter((iso) => {
            const lv = live.countries[iso];
            return lv && WGI_KEYS.some((k) => typeof lv[k] === "number");
          }).length;
          info = { period: live.period, covered, total: codes.length, live: covered > 0 };
        }
      } catch {
        /* keep fixture — degradación elegante */
      }

      const [w, ...scores] = await Promise.all([
        getWeights(),
        ...codes.map((c) => scoreCountry(c, merged)),
      ]);
      const map: Record<string, IRMPResult> = {};
      scores.forEach((s) => (map[s.country_code] = s));
      setWeights(w);
      setResults(map);
      setDataset(merged);
      setWgiInfo(info);
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
      sub="Índice de Riesgo Macro-Político (IRMP): mayor score = menor riesgo. Determinista y auditable. Gobernanza (WGI) en vivo del Banco Mundial; resto del conjunto regional ilustrativo."
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
  const rows: DimensionRow[] = cur
    ? Object.entries(cur.dimensions).map(([key, d]) => ({
        key,
        label: DIMENSION_LABELS[key] ?? key,
        score: d.score,
        weight: d.weight,
        contribution: d.contribution,
      }))
    : [];

  const ranking = [...codes]
    .map((c) => results[c])
    .filter(Boolean)
    .sort((a, b) => b.irmp_score - a.irmp_score);

  const doSave = async () => {
    setSaved(null);
    try {
      await saveSnapshot(selected, dataset, periodEndFor(period), COUNTRY_NAMES[selected]);
      setSaved(`Snapshot guardado (${periodEndFor(period)}) · evento irmp.updated publicado`);
    } catch {
      setSaved("No se pudo guardar el snapshot.");
    }
  };

  return (
    <div>
      <PageHead
        eyebrow="WGI · BCRD · SIB"
        title="Regulatorio & político"
        sub="Índice de Riesgo Macro-Político (IRMP): mayor score = menor riesgo. Determinista y auditable. Gobernanza (WGI) en vivo del Banco Mundial; resto del conjunto regional ilustrativo."
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
            {wgiInfo.live ? (
              <Chip tone="ok">
                WGI en vivo · {wgiInfo.period} · {wgiInfo.covered}/{wgiInfo.total} países
              </Chip>
            ) : (
              <Chip tone="muted">WGI ilustrativo · sync pendiente</Chip>
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
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { GitCompare, Plus, X, Landmark, ArrowRight } from "lucide-react";
import client from "@/shared/api/client";
import {
  PageHead,
  Card,
  CardHead,
  StateBlock,
  Chip,
  Gauge,
  BandBadge,
  Tabs,
  Skeleton,
} from "@/shared/ui/primitives";
import { AiInsightCard } from "@/shared/ui/AiInsightCard";
import { bandFor, riskBandFor, type Band } from "@/shared/lib/bands";
import { fmtNum } from "@/shared/lib/format";
import { COUNTRY_NAMES } from "@/modules/macro-political-risk/data";
import { REGION_NAMES } from "@/modules/social-dev/data";
import { getCompareInsight, type CompareInsightItem } from "../api";

/* ──────────────────────────────────────────────────────────────────
 * Comparador cross-eje. Un selector de dominio (Sectorial · Regulatorio ·
 * Social · ESG) → 2–4 ítems lado a lado por su score + desglose por dimensión
 * + insight IA comparativo. Banca tiene su comparador dedicado (link abajo).
 * Tira de los endpoints existentes vía el client compartido; cero fabricación
 * (un ítem sin score persistido se rotula «Sin score», no se inventa).
 * ────────────────────────────────────────────────────────────────── */

const MAX = 4;

const DIM_LABELS: Record<string, string> = {
  macro: "Macroeconómica", external: "Externa", political: "Político-institucional",
  regulatory: "Regulatoria", regulation: "Regulación", events: "Eventos", business: "Negocios",
  talent: "Talento", sector: "Sector", health: "Salud", education: "Educación",
  living_standards: "Nivel de vida", inclusion: "Inclusión",
  physical_risk: "Riesgo físico", transition_risk: "Riesgo de transición",
  adaptive_capacity: "Capacidad de adaptación", governance: "Gobernanza",
  solidez: "Solidez", calidad: "Calidad", eficiencia: "Eficiencia", liquidez: "Liquidez",
  diversificacion: "Diversificación",
};
const dimLabel = (k: string) => DIM_LABELS[k] ?? k.replace(/_/g, " ");

interface CompItem { id: string; name: string; }
interface Dim { key: string; label: string; score: number; weight: number; contribution: number; }
interface Scored { score: number; band: Band; dims: Dim[]; }

type RawDims = Record<string, { score: number; weight: number; contribution: number }>;
function mapDims(rec: RawDims): Dim[] {
  return Object.entries(rec || {}).map(([k, v]) => ({
    key: k, label: dimLabel(k), score: v.score, weight: v.weight, contribution: v.contribution,
  }));
}

type ScoreFn = (id: string) => Promise<Scored | null>;
interface Domain {
  key: string;
  tab: string;
  eyebrow: string;
  noun: string;       // plural, p. ej. "sectores"
  singular: string;   // p. ej. "sector"
  ejeLabel: string;
  load: () => Promise<{ items: CompItem[]; score: ScoreFn }>;
}

/* eslint-disable @typescript-eslint/no-explicit-any */
const DOMAINS: Domain[] = [
  {
    key: "sectorial", tab: "Sectorial", eyebrow: "BCRD · IAI", noun: "sectores", singular: "sector",
    ejeLabel: "Sectorial — IAI (atractivo de inversión)",
    load: async () => {
      const { data } = await client.get("/sector-intel/sectors");
      const items = ((data.sectors as any[]) || [])
        .map((s) => ({ id: s.code, name: s.name }))
        .sort((a, b) => a.name.localeCompare(b.name));
      return {
        items,
        score: async (id) => {
          const { data: d } = await client.get(`/sector-intel/${id}/latest`);
          if (!d?.has_score) return null;
          return { score: d.iai_score, band: bandFor(d.iai_score), dims: mapDims(d.iai_breakdown) };
        },
      };
    },
  },
  {
    key: "regulatorio", tab: "Regulatorio", eyebrow: "WGI · IRMP", noun: "países", singular: "país",
    ejeLabel: "Regulatorio & político — IRMP (mayor score = menor riesgo)",
    load: async () => {
      const { data } = await client.get("/macro-political-risk/dataset");
      const ds = (data.dataset as Record<string, Record<string, number>>) || {};
      const items = Object.keys(ds)
        .map((code) => ({ id: code, name: COUNTRY_NAMES[code] ?? code }))
        .sort((a, b) => a.name.localeCompare(b.name));
      return {
        items,
        score: async (id) => {
          const { data: d } = await client.post("/macro-political-risk/score", {
            country_code: id, dataset: ds, country_name: COUNTRY_NAMES[id],
          });
          if (d?.irmp_score == null) return null;
          return { score: d.irmp_score, band: riskBandFor(d.irmp_score), dims: mapDims(d.dimensions) };
        },
      };
    },
  },
  {
    key: "social", tab: "Social", eyebrow: "ONE · IDM", noun: "regiones", singular: "región",
    ejeLabel: "Social & desarrollo — IDM",
    load: async () => {
      const { data } = await client.get("/social-dev/indicators");
      const rows = (data.indicators as any[]) || [];
      const map = new Map<string, any>(rows.map((r) => [r.entity_key, r]));
      const items = rows
        .map((r) => ({ id: r.entity_key, name: REGION_NAMES[r.entity_key] ?? r.entity_key }))
        .sort((a, b) => a.name.localeCompare(b.name));
      return {
        items,
        score: async (id) => {
          const r = map.get(id);
          if (!r) return null;
          return { score: r.development_score, band: bandFor(r.development_score), dims: mapDims(r.breakdown) };
        },
      };
    },
  },
  {
    key: "esg", tab: "ESG", eyebrow: "ND-GAIN · IRC", noun: "países", singular: "país",
    ejeLabel: "ESG & clima — IRC (resiliencia climática)",
    load: async () => {
      const { data } = await client.get("/esg-climate/indicators");
      const items = ((data.indicators as any[]) || [])
        .map((i) => ({ id: i.entity_key, name: i.country_name }))
        .sort((a, b) => a.name.localeCompare(b.name));
      return {
        items,
        score: async (id) => {
          const { data: d } = await client.get("/esg-climate/score", { params: { entity_key: id } });
          if (!d?.has_score || !d?.breakdown) return null;
          return { score: d.esg_score, band: bandFor(d.esg_score), dims: mapDims(d.breakdown.dimensions) };
        },
      };
    },
  },
];
/* eslint-enable @typescript-eslint/no-explicit-any */

interface ResultRow { item: CompItem; scored: Scored | null; }

export function ComparadorPage() {
  const [domainKey, setDomainKey] = useState<string>(DOMAINS[0].key);
  const domain = DOMAINS.find((d) => d.key === domainKey) ?? DOMAINS[0];

  const [items, setItems] = useState<CompItem[]>([]);
  const scoreFnRef = useRef<ScoreFn | null>(null);
  const [listStatus, setListStatus] = useState<"loading" | "error" | "ready">("loading");
  const [slots, setSlots] = useState<string[]>(["", ""]);
  const [results, setResults] = useState<ResultRow[]>([]);
  const [comparing, setComparing] = useState(false);
  const runSeq = useRef(0);

  useEffect(() => {
    let active = true;
    runSeq.current++; // invalida cualquier comparación en vuelo del dominio anterior
    setListStatus("loading");
    setItems([]);
    setSlots(["", ""]);
    setResults([]);
    scoreFnRef.current = null;
    domain
      .load()
      .then(({ items: its, score }) => {
        if (!active) return;
        setItems(its);
        scoreFnRef.current = score;
        setListStatus(its.length ? "ready" : "error");
      })
      .catch(() => active && setListStatus("error"));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [domainKey]);

  const selectedIds = [...new Set(slots.filter(Boolean))];
  const canCompare = selectedIds.length >= 2 && !!scoreFnRef.current;

  const run = async () => {
    if (!canCompare || !scoreFnRef.current) return;
    const seq = ++runSeq.current;
    setComparing(true);
    try {
      const fn = scoreFnRef.current;
      const rows = await Promise.all(
        selectedIds.slice(0, MAX).map(async (id) => {
          const item = items.find((i) => i.id === id) ?? { id, name: id };
          const scored = await fn(id).catch(() => null);
          return { item, scored } as ResultRow;
        }),
      );
      if (runSeq.current !== seq) return; // dominio cambió / corrida más nueva → descartar
      setResults(rows);
    } finally {
      if (runSeq.current === seq) setComparing(false);
    }
  };

  const setSlot = (idx: number, val: string) =>
    setSlots((s) => s.map((v, i) => (i === idx ? val : v)));

  const scoredRows = results.filter((r) => r.scored);
  const dimRows = scoredRows[0]?.scored?.dims ?? [];
  const aiItems: CompareInsightItem[] = scoredRows.map((r) => ({
    nombre: r.item.name,
    score: r.scored!.score,
    banda: r.scored!.band.label,
    dimensiones: Object.fromEntries(r.scored!.dims.map((d) => [d.label, Number(d.score.toFixed(1))])),
  }));
  const aiKey = `${domainKey}|${results.map((r) => r.item.id).join("-")}`;

  return (
    <div>
      <PageHead
        eyebrow="Herramientas"
        title="Comparador"
        sub="Compara 2–4 sectores, países o regiones por su score de índice y su desglose por dimensión, con una lectura comparativa de IA."
      />

      <div className="mb-5">
        <Tabs
          tabs={DOMAINS.map((d) => ({ id: d.key, label: d.tab }))}
          active={domainKey}
          onChange={setDomainKey}
        />
      </div>

      {/* Selector de ítems */}
      <Card className="mb-5">
        <div className="flex items-center justify-between gap-3 mb-3">
          <p className="text-sm text-muted">
            Selecciona 2–4 {domain.noun} <span className="text-faint">· {domain.eyebrow}</span>
          </p>
        </div>

        {listStatus === "loading" ? (
          <div className="space-y-2">
            <Skeleton className="h-9 w-72" />
            <Skeleton className="h-9 w-72" />
          </div>
        ) : listStatus === "error" ? (
          <StateBlock kind="error" message={`No se pudieron cargar los ${domain.noun}.`} />
        ) : (
          <>
            <div className="space-y-2.5 mb-4">
              {slots.map((slot, idx) => (
                <div key={idx} className="flex items-center gap-3">
                  <select
                    className="field w-72"
                    aria-label={`${domain.singular} ${idx + 1}`}
                    value={slot}
                    onChange={(e) => setSlot(idx, e.target.value)}
                  >
                    <option value="">— elegir —</option>
                    {items.map((it) => (
                      <option
                        key={it.id}
                        value={it.id}
                        disabled={slots.includes(it.id) && slot !== it.id}
                      >
                        {it.name}
                      </option>
                    ))}
                  </select>
                  {slots.length > 2 && (
                    <button
                      onClick={() => setSlots((s) => s.filter((_, i) => i !== idx))}
                      className="text-faint hover:text-alert"
                      title="Quitar"
                      aria-label="Quitar"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  )}
                </div>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-4">
              {slots.length < MAX && (
                <button
                  onClick={() => setSlots((s) => [...s, ""])}
                  className="text-sm text-accent-ink hover:underline flex items-center gap-1"
                >
                  <Plus className="w-3.5 h-3.5" /> Añadir {domain.singular}
                </button>
              )}
              <button onClick={run} disabled={!canCompare || comparing} className="btn btn-primary">
                <GitCompare className="w-4 h-4" />
                {comparing ? "Comparando…" : "Comparar"}
              </button>
            </div>
          </>
        )}
      </Card>

      {/* Resultados */}
      {results.length === 0 ? (
        <StateBlock
          kind="empty"
          message={`Selecciona al menos dos ${domain.noun} y ejecuta la comparación.`}
        />
      ) : (
        <div className="space-y-5">
          <div
            className={`grid gap-4 ${
              results.length === 2 ? "grid-cols-2" : results.length === 3 ? "grid-cols-3" : "grid-cols-2 lg:grid-cols-4"
            }`}
          >
            {results.map(({ item, scored }) => (
              <Card key={item.id} className="flex flex-col items-center text-center">
                <p className="text-sm text-ink mb-2 truncate w-full">{item.name}</p>
                {scored ? (
                  <>
                    <Gauge score={scored.score} band={scored.band} size={104} />
                    <div className="mt-2">
                      <BandBadge band={scored.band} />
                    </div>
                  </>
                ) : (
                  <div className="py-6">
                    <Chip tone="muted">Sin score</Chip>
                    <p className="text-xs text-faint mt-2">No hay score persistido para este período.</p>
                  </div>
                )}
              </Card>
            ))}
          </div>

          {dimRows.length > 0 && (
            <Card>
              <CardHead icon={GitCompare} title="Detalle por dimensión" subtitle={domain.ejeLabel} />
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-muted border-b border-line">
                      <th className="py-2 px-2 font-medium">Dimensión</th>
                      {results.map(({ item }) => (
                        <th key={item.id} className="py-2 px-2 font-medium text-right truncate">
                          {item.name}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {dimRows.map((dim) => (
                      <tr key={dim.key} className="border-b border-line/60">
                        <td className="py-2 px-2 text-body">{dim.label}</td>
                        {results.map(({ item, scored }) => {
                          const v = scored?.dims.find((d) => d.key === dim.key)?.score;
                          return (
                            <td key={item.id} className="py-2 px-2 text-right mono text-ink tabular-nums">
                              {v == null ? "—" : fmtNum(v, 1)}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                    <tr className="border-t-2 border-line">
                      <td className="py-2 px-2 font-semibold text-ink">Score general</td>
                      {results.map(({ item, scored }) => (
                        <td key={item.id} className="py-2 px-2 text-right mono font-bold text-ink tabular-nums">
                          {scored ? fmtNum(scored.score, 1) : "—"}
                        </td>
                      ))}
                    </tr>
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {aiItems.length >= 2 && (
            <AiInsightCard
              title="Análisis comparativo (IA)"
              subtitle={`Fortalezas y debilidades relativas · ${domain.ejeLabel}`}
              icon={GitCompare}
              depsKey={aiKey}
              fetcher={() => getCompareInsight(domain.ejeLabel, aiItems)}
            />
          )}
        </div>
      )}

      {/* Banca tiene su comparador dedicado (radar + sub-componentes) */}
      <Card className="mt-5">
        <div className="flex items-center gap-3">
          <span className="shrink-0 grid place-items-center w-[30px] h-[30px] rounded-[9px] bg-accent-soft text-accent">
            <Landmark size={16} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-ink">¿Comparar entidades bancarias?</div>
            <p className="text-xs text-muted mt-0.5">
              La banca tiene su comparador dedicado, con radar y sub-componentes del rating.
            </p>
          </div>
          <Link
            to="/banking-score/compare"
            className="shrink-0 text-sm text-accent-ink hover:underline flex items-center gap-1"
          >
            Abrir <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      </Card>
    </div>
  );
}

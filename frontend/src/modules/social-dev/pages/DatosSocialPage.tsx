import { useEffect, useState } from "react";
import { Users } from "lucide-react";
import { Card, CardHead, StatTile, StateBlock, Chip } from "@/shared/ui/primitives";
import { fmtNum } from "@/shared/lib/format";
import { OperationsConsole } from "@/shared/ops/OperationsConsole";
import { getIndicators, getDataset, IndicatorsResult, IdmDataset } from "../api";
import { DIM_LABELS, IDM_DIM_VARS } from "../data";

// The social-dev data operations.
const SOCIAL_OPS = new Set([
  "one-social-sync",
  "idm-snapshot",
  "one-education-extract",
  "one-publications-sync",
]);

/** real / parcial / rúbrica for an IDM dimension, from the dataset's source map. */
function dimProvenance(dimKey: string, sources: Record<string, string> | undefined) {
  const vars = IDM_DIM_VARS[dimKey] ?? [];
  if (!sources || vars.length === 0) return { text: "—", tone: "muted" as const };
  const live = vars.filter((v) => sources[v] === "live").length;
  if (live === 0) return { text: "rúbrica", tone: "muted" as const };
  if (live === vars.length) return { text: "real", tone: "ok" as const };
  return { text: "parcial", tone: "warn" as const };
}

/** "Estado del dato" panel: coverage + per-dimension provenance of the IDM. */
function SocialOverview() {
  const [ind, setInd] = useState<IndicatorsResult | null>(null);
  const [ds, setDs] = useState<IdmDataset | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    Promise.all([getIndicators(), getDataset()])
      .then(([i, d]) => { setInd(i); setDs(d); setState("ready"); })
      .catch(() => setState("error"));
  }, []);

  if (state === "loading")
    return <Card><StateBlock kind="loading" message="Cargando estado del dato…" /></Card>;
  if (state === "error")
    return <Card><StateBlock kind="error" message="No se pudo leer el estado del dato social." /></Card>;

  const count = ind?.count ?? 0;
  // Provenance is uniform across regions; sample the first region's source map.
  const firstRegion = ds ? Object.keys(ds.sources)[0] : undefined;
  const sources = firstRegion ? ds!.sources[firstRegion] : undefined;

  return (
    <Card>
      <CardHead
        icon={Users}
        title="Estado del dato"
        subtitle="Cobertura del IDM y procedencia real-vs-rúbrica por dimensión"
        right={<Chip tone={count > 0 ? "ok" : "muted"}>{count > 0 ? "IDM calculado" : "Sin dato"}</Chip>}
      />
      {count === 0 ? (
        <p className="text-sm text-muted mt-3">
          Aún no hay IDM. Ejecuta «Sincronizar social (ONE)» y luego «Backfill del IDM» abajo.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-3">
            <StatTile label="Regiones" value={count} />
            <StatTile label="Período" value={ind?.period ?? "—"} />
            <StatTile label="IDM promedio" value={fmtNum(ind?.distribution?.mean ?? null, 1)} />
            <StatTile label="Dispersión" value={fmtNum(ind?.distribution?.spread ?? null, 1)} />
          </div>
          <div className="mt-4">
            <div className="text-xs text-muted mb-2">Procedencia por dimensión</div>
            <div className="flex flex-wrap gap-2">
              {Object.keys(IDM_DIM_VARS).map((dim) => {
                const p = dimProvenance(dim, sources);
                return (
                  <Chip key={dim} tone={p.tone}>
                    {DIM_LABELS[dim] ?? dim}: {p.text}
                  </Chip>
                );
              })}
            </div>
          </div>
        </>
      )}
    </Card>
  );
}

/** Datos · Social (ONE): estado del dato + operaciones de ingesta/cálculo. */
export function DatosSocialPage() {
  return (
    <OperationsConsole
      eyebrow="Datos · Social"
      title="Social · ONE"
      sub="Ingesta y cálculo del desarrollo social: pobreza por región (ONE), salud (WDI), educación del ENHOGAR, estudios de la ONE e índice IDM."
      filter={(op) => SOCIAL_OPS.has(op.name)}
      emptyMessage="No hay operaciones de Social registradas."
      overview={<SocialOverview />}
    />
  );
}

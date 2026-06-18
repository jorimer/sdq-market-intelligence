import { useEffect, useState } from "react";
import { Boxes } from "lucide-react";
import { Card, CardHead, StatTile, StateBlock, Chip } from "@/shared/ui/primitives";
import { fmtNum, fmtPct } from "@/shared/lib/format";
import { OperationsConsole } from "@/shared/ops/OperationsConsole";
import { getTradeScore, TradeScore } from "../api";

/** "Estado del dato" panel: coverage + provenance of the persisted DGA trade data. */
function ComercioOverview() {
  const [score, setScore] = useState<TradeScore | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    getTradeScore()
      .then((s) => { setScore(s); setState("ready"); })
      .catch(() => setState("error"));
  }, []);

  if (state === "loading")
    return <Card><StateBlock kind="loading" message="Cargando estado del dato…" /></Card>;
  if (state === "error")
    return <Card><StateBlock kind="error" message="No se pudo leer el estado del dato comercial." /></Card>;

  const s = score!;
  return (
    <Card>
      <CardHead
        icon={Boxes}
        title="Estado del dato"
        subtitle="Cobertura y procedencia del último snapshot comercial"
        right={<Chip tone={s.has_score ? "ok" : "muted"}>{s.has_score ? "Dato real (DGA)" : "Sin dato"}</Chip>}
      />
      {!s.has_score ? (
        <p className="text-sm text-muted mt-3">
          Aún no hay datos. Ejecuta «Sincronizar comercio (Aduanas/DGA)» abajo para ingerir
          las estadísticas por capítulo arancelario.
        </p>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-3">
          <StatTile label="Último período" value={s.period ?? "—"} />
          <StatTile label="Capítulos export." value={s.n_products_export ?? "—"} />
          <StatTile label="Export. total" value={fmtNum(s.total_exports, 0)} unit="M US$" />
          <StatTile label="Import. total" value={fmtNum(s.total_imports, 0)} unit="M US$" />
          <StatTile label="Resiliencia" value={fmtNum(s.resilience_score, 1)} />
          <StatTile label="Diversificación" value={fmtNum(s.export_diversification, 1)} />
          <StatTile
            label="Dep. importaciones"
            value={s.import_dependency != null ? fmtPct(s.import_dependency * 100, 0) : "—"}
          />
          <StatTile label="Fuente" value="DGA · Aduanas" />
        </div>
      )}
    </Card>
  );
}

/** Datos · Comercio (DGA/Aduanas): estado del dato + operación de sync. */
export function DatosComercioPage() {
  return (
    <OperationsConsole
      eyebrow="Datos · Comercio"
      title="Comercio · DGA (Aduanas)"
      sub="Ingesta de las estadísticas de comercio exterior por capítulo arancelario de la DGA (Data Cruda, exportaciones + importaciones, trimestral)."
      filter={(op) => op.name.startsWith("dga-")}
      emptyMessage="No hay operaciones de Comercio registradas."
      overview={<ComercioOverview />}
    />
  );
}

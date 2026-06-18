import { OperationsConsole } from "@/shared/ops/OperationsConsole";

// The governance/IRMP data operations (WGI ingest, IRMP snapshot + backtest,
// GDELT instability events).
const GOV_OPS = new Set([
  "wgi-sync",
  "irmp-snapshot",
  "irmp-backtest",
  "gdelt-sync",
  "gdelt-bq-sync",
]);

/** Datos · Gobernanza (WGI): trigger/monitor/schedule the IRMP data operations. */
export function DatosGobernanzaPage() {
  return (
    <OperationsConsole
      eyebrow="Datos · Gobernanza"
      title="Gobernanza · WGI"
      sub="Ingesta de gobernanza (Worldwide Governance Indicators del Banco Mundial), cálculo del IRMP por país, eventos de inestabilidad (GDELT) y backtest de la metodología."
      filter={(op) => GOV_OPS.has(op.name)}
      emptyMessage="No hay operaciones de Gobernanza registradas."
    />
  );
}

import { useTranslation } from "react-i18next";
import { OperationsConsole } from "@/shared/ops/OperationsConsole";
import { SovereignPanelCard } from "../components/SovereignPanelCard";

// The governance/IRMP data operations (WGI ingest, IRMP snapshot + backtest,
// GDELT instability events, sovereign ratings refresh).
const GOV_OPS = new Set([
  "wgi-sync",
  "irmp-snapshot",
  "irmp-backtest",
  "gdelt-sync",
  "gdelt-bq-sync",
  "sovereign-ratings-sync",
]);

/** Datos · Gobernanza (WGI): trigger/monitor/schedule the IRMP data operations, plus the
 * sovereign ratings panel — where the freshness proposal ("verify + annotate the
 * affirmation") gets completed. */
export function DatosGobernanzaPage() {
  const { t } = useTranslation();
  return (
    <OperationsConsole
      eyebrow={t("datos.gobernanza.eyebrow")}
      title={t("datos.gobernanza.title")}
      sub={t("datos.gobernanza.sub")}
      filter={(op) => GOV_OPS.has(op.name)}
      emptyMessage={t("datos.gobernanza.empty")}
      overview={<SovereignPanelCard />}
    />
  );
}

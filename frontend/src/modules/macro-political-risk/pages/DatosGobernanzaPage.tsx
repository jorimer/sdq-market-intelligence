import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
  return (
    <OperationsConsole
      eyebrow={t("datos.gobernanza.eyebrow")}
      title={t("datos.gobernanza.title")}
      sub={t("datos.gobernanza.sub")}
      filter={(op) => GOV_OPS.has(op.name)}
      emptyMessage={t("datos.gobernanza.empty")}
    />
  );
}
